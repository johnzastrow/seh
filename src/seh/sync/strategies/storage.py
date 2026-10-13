"""Storage (battery) sync strategy."""

from datetime import datetime, timedelta
from typing import Any

import structlog

from seh.db.repositories.battery import BatteryRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.sync.v2_fields import model_name, site_local

logger = structlog.get_logger(__name__)

# The V2 storage telemetry schema has not been observed live (the verified site has no
# battery). Metric names follow a community V2 client; the first one present is used.
POWER_METRICS = ("power", "chargePower")
DISCHARGE_METRIC = "dischargePower"
CHARGE_LEVEL_METRICS = ("stateOfEnergy", "stateOfCharge", "chargeLevel")


def _latest(metrics: dict[str, Any], name: str) -> tuple[datetime | None, Any]:
    """(timestamp, value) of the newest non-null point of one metric series."""
    series = metrics.get(name) or {}
    for point in reversed(series.get("values") or []):
        if point.get("value") is not None:
            return site_local(point.get("timestamp")), point["value"]
    return None, None


class StorageSyncStrategy(BaseSyncStrategy):
    """Sync strategy for batteries (device list + GET /sites/{id}/storage/telemetry)."""

    data_type = "storage"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync battery devices and their latest state.

        Sites without a battery make no telemetry call, so this costs no API credit
        beyond the shared device list.

        Args:
            site_id: Site ID.
            full: Ignored (only the latest state is stored).

        Returns:
            Number of batteries synced.
        """
        logger.info("Syncing storage data", site_id=site_id)

        try:
            devices = await self.client.get_devices(site_id)
            batteries = [d for d in devices if d.get("type") == "BATTERY" and d.get("serialNumber")]
            if not batteries:
                logger.info("No batteries for site", site_id=site_id)
                self.update_sync_metadata(site_id, datetime.now(), 0)
                return 0

            end_time = datetime.now()
            telemetry = await self.client.get_storage_telemetry(
                site_id, end_time - timedelta(days=1), end_time, resolution="QUARTER_HOUR"
            )

            repo = BatteryRepository(self.session)
            for device in batteries:
                serial = device["serialNumber"]
                db_data: dict[str, Any] = {
                    "site_id": site_id,
                    "serial_number": serial,
                    "name": device.get("name"),
                    "manufacturer": device.get("manufacturer"),
                    "model": model_name(device),
                    "firmware_version": device.get("firmwareVersion"),
                    "nameplate_capacity": device.get("nameplate"),
                    "connected_inverter_sn": device.get("connectedTo"),
                }

                metrics = telemetry.get(serial) or {}
                when, power = next(
                    (r for m in POWER_METRICS if (r := _latest(metrics, m))[1] is not None),
                    (None, None),
                )
                _, discharge = _latest(metrics, DISCHARGE_METRIC)
                if power is not None and discharge:
                    power = power - discharge  # positive = charging, as in V1
                _, level = next(
                    (r for m in CHARGE_LEVEL_METRICS if (r := _latest(metrics, m))[1] is not None),
                    (None, None),
                )
                if when is not None:
                    db_data.update(
                        last_power=power, last_state_of_charge=level, last_telemetry_time=when
                    )

                repo.upsert(db_data)

            self.update_sync_metadata(site_id, datetime.now(), len(batteries))
            logger.info("Storage sync complete", site_id=site_id, batteries=len(batteries))
            return len(batteries)

        except Exception as e:
            if self.skip_if_unavailable(site_id, e):
                return 0
            logger.error("Storage sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
