"""Meter sync strategy."""

from datetime import datetime, timedelta
from typing import Any

import structlog

from seh.db.repositories.meter import MeterReadingRepository, MeterRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.sync.v2_fields import model_name, site_local

logger = structlog.get_logger(__name__)

# V2 reports one physical meter with a series per direction. Each direction is stored as a
# logical meter named like the V2/V1 device of that role, with V1's meter type.
FAMILIES: dict[str, tuple[str, str]] = {
    # V2 metric prefix: (seh_meters.name, seh_meters.meter_type)
    "production": ("Production Meter", "Production"),
    "import": ("Import Meter", "Purchased"),
    "export": ("Export Meter", "FeedIn"),
}

# Name keyword -> V1 meter type, for the device list (includes virtual meters).
TYPE_BY_KEYWORD = (
    ("self consumption", "SelfConsumption"),
    ("consumption", "Consumption"),
    ("production", "Production"),
    ("import", "Purchased"),
    ("export", "FeedIn"),
)


def meter_type_for(name: str) -> str | None:
    lowered = name.lower()
    return next((t for keyword, t in TYPE_BY_KEYWORD if keyword in lowered), None)


class MeterSyncStrategy(BaseSyncStrategy):
    """Sync strategy for meters (device list) and meter readings (meters/telemetry)."""

    data_type = "meter"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync meters and their 15-minute power readings.

        V2 meter telemetry has no voltage, current, power factor, or lifetime energy, so
        readings carry power only (W, 15-minute average).

        Args:
            site_id: Site ID.
            full: If True, sync from lookback date regardless of last sync.

        Returns:
            Number of readings synced.
        """
        logger.info("Syncing meter data", site_id=site_id, full=full)

        try:
            devices = await self.client.get_devices(site_id)
            meter_devices = [d for d in devices if d.get("type") == "METER" and d.get("name")]

            meter_repo = MeterRepository(self.session)
            for device in meter_devices:
                meter_repo.upsert(
                    {
                        "site_id": site_id,
                        "name": device["name"],
                        "manufacturer": device.get("manufacturer"),
                        "model": model_name(device),
                        "meter_type": meter_type_for(str(device["name"])),
                        "serial_number": device.get("serialNumber"),
                        "connection_type": device.get("connectedTo"),
                    }
                )

            end_time = datetime.now()
            if full:
                start_time = end_time - timedelta(days=self.settings.power_lookback_days)
            else:
                start_time = self.get_start_time(site_id, self.settings.power_lookback_days)

            telemetry = await self.client.get_meters_telemetry(
                site_id, start_time, end_time, resolution="QUARTER_HOUR"
            )

            reading_repo = MeterReadingRepository(self.session)
            count = 0
            latest: datetime | None = None
            for serial, metrics in telemetry.items():
                device = next((d for d in meter_devices if d.get("serialNumber") == serial), {})
                for prefix, (name, meter_type) in FAMILIES.items():
                    series: dict[str, Any] = metrics.get(f"{prefix}Power") or {}
                    values = series.get("values") or []
                    if not values:
                        continue
                    if len(telemetry) > 1:
                        name = f"{name} {serial}"  # keep several physical meters apart
                    meter = meter_repo.upsert(
                        {
                            "site_id": site_id,
                            "name": name,
                            "manufacturer": device.get("manufacturer"),
                            "model": model_name(device),
                            "meter_type": meter_type,
                            "serial_number": serial,
                            "connection_type": device.get("connectedTo"),
                        }
                    )
                    readings = []
                    for point in values:
                        timestamp = site_local(point.get("timestamp"))
                        if timestamp is None or point.get("value") is None:
                            continue
                        readings.append(
                            {"meter_id": meter.id, "timestamp": timestamp, "power": point["value"]}
                        )
                        latest = timestamp if latest is None or timestamp > latest else latest
                    if readings:
                        count += reading_repo.upsert_batch(readings)

            self.update_sync_metadata(site_id, latest, count)
            logger.info("Meter sync complete", site_id=site_id, count=count)
            return count

        except Exception as e:
            if self.skip_if_unavailable(site_id, e):
                return 0
            logger.error("Meter sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
