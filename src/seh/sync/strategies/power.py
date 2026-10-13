"""Power sync strategy."""

from datetime import datetime, timedelta
from typing import Any

import structlog

from seh.db.repositories.power import PowerFlowRepository, PowerRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.sync.v2_fields import site_local

logger = structlog.get_logger(__name__)


def _activity(component: dict[str, Any]) -> str | None:
    """V1-style status: "Active" when the component is moving power, otherwise "Idle".

    V2's `active` flag only says the component exists (PV stays active at night with
    0 kW), whereas V1 reported "Idle" whenever the power was zero.
    """
    active = component.get("active")
    power = component.get("power")
    if active is None and power is None:
        return None
    if not active or not power:
        return "Idle"
    return "Active"


class PowerSyncStrategy(BaseSyncStrategy):
    """Sync strategy for power readings (GET /sites/{id}/power) and the power flow snapshot."""

    data_type = "power"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync 15-minute average power, then the current power flow snapshot.

        The client splits the range into SolarEdge's maximum windows (1 week for
        QUARTER_HOUR) and merges the results.

        Args:
            site_id: Site ID.
            full: If True, sync from lookback date regardless of last sync.

        Returns:
            Number of power readings synced.
        """
        logger.info("Syncing power data", site_id=site_id, full=full)

        try:
            end_time = datetime.now()
            if full:
                start_time = end_time - timedelta(days=self.settings.power_lookback_days)
            else:
                start_time = self.get_start_time(site_id, self.settings.power_lookback_days)

            values = await self.client.get_power(
                site_id, start_time, end_time, resolution=self.settings.power_time_unit
            )

            readings = []
            latest: datetime | None = None
            for value in values:
                timestamp = site_local(value.get("timestamp"))
                power_watts = value.get("value")
                if timestamp is None or power_watts is None:
                    continue  # None marks intervals without data yet
                readings.append(
                    {"site_id": site_id, "timestamp": timestamp, "power_watts": power_watts}
                )
                latest = timestamp if latest is None or timestamp > latest else latest

            count = PowerRepository(self.session).upsert_batch(readings) if readings else 0

            await self._sync_power_flow(site_id)

            # The next incremental sync restarts from the newest reading (minus the overlap),
            # so a partially filled last interval is fetched again and completed.
            self.update_sync_metadata(site_id, latest, count)
            logger.info("Power sync complete", site_id=site_id, count=count)
            return count

        except Exception as e:
            logger.error("Power sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise

    async def _sync_power_flow(self, site_id: int) -> None:
        """Store the current power flow snapshot (GET /sites/{id}/power-flow, kW).

        V2 reports grid direction as status IMPORT/EXPORT; seh_power_flows keeps V1's
        meaning (grid_status is "Active"/"Idle"), so direction is not stored.

        Args:
            site_id: Site ID.
        """
        try:
            flow = await self.client.get_power_flow(site_id)
            if not flow:
                return

            pv: dict[str, Any] = flow.get("pv") or {}
            load: dict[str, Any] = flow.get("load") or {}
            grid: dict[str, Any] = flow.get("grid") or {}
            storage: dict[str, Any] = flow.get("storage") or {}

            db_data = {
                "site_id": site_id,
                "timestamp": site_local(flow.get("updatedAt")) or datetime.now(),
                "unit": flow.get("unit"),
                "grid_status": _activity(grid),
                "grid_power": grid.get("power"),
                "pv_status": _activity(pv),
                "pv_power": pv.get("power"),
                "load_status": _activity(load),
                "load_power": load.get("power"),
                "storage_status": storage.get("status"),
                "storage_power": storage.get("power"),
                "storage_charge_level": storage.get("chargeLevel"),
            }
            PowerFlowRepository(self.session).upsert(db_data)

        except Exception as e:
            # Power flow is optional (Advanced Monitoring on some plans); never fail the sync.
            logger.warning("Power flow sync failed", site_id=site_id, error=str(e))
