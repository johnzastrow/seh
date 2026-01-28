"""Power sync strategy."""

from datetime import datetime, timedelta

import structlog

from seh.db.repositories.power import PowerFlowRepository, PowerRepository
from seh.sync.strategies.base import BaseSyncStrategy

logger = structlog.get_logger(__name__)


class PowerSyncStrategy(BaseSyncStrategy):
    """Sync strategy for power data."""

    data_type = "power"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync power production data.

        Args:
            site_id: Site ID.
            full: If True, sync from lookback date regardless of last sync.

        Returns:
            Number of records synced.
        """
        logger.info("Syncing power data", site_id=site_id, full=full)

        try:
            # Determine time range
            end_time = datetime.now()

            if full:
                start_time = end_time - timedelta(days=self.settings.power_lookback_days)
            else:
                start_time = self.get_start_time(site_id, self.settings.power_lookback_days)

            # Power API limits to 1 month at a time
            total_count = 0
            current_start = start_time
            latest_timestamp: datetime | None = None

            while current_start < end_time:
                # Calculate chunk end (max 1 month)
                chunk_end = min(current_start + timedelta(days=30), end_time)

                chunk_count = await self._sync_chunk(
                    site_id, current_start, chunk_end
                )
                total_count += chunk_count

                if chunk_count > 0:
                    latest_timestamp = chunk_end

                current_start = chunk_end

            # Also sync current power flow
            await self._sync_power_flow(site_id)

            self.update_sync_metadata(site_id, latest_timestamp, total_count)
            logger.info("Power sync complete", site_id=site_id, count=total_count)
            return total_count

        except Exception as e:
            logger.error("Power sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise

    async def _sync_chunk(
        self,
        site_id: int,
        start_time: datetime,
        end_time: datetime,
    ) -> int:
        """Sync a chunk of power data.

        Args:
            site_id: Site ID.
            start_time: Chunk start time.
            end_time: Chunk end time.

        Returns:
            Number of records synced.
        """
        power_values = await self.client.get_power(
            site_id=site_id,
            start_time=start_time,
            end_time=end_time,
        )

        if not power_values:
            return 0

        repo = PowerRepository(self.session)
        readings = []

        for value in power_values:
            date_str = value.get("date")
            if not date_str:
                continue

            try:
                timestamp = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    timestamp = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    logger.warning("Invalid timestamp format", timestamp=date_str)
                    continue

            power_watts = value.get("value")
            if power_watts is None:
                continue

            readings.append({
                "site_id": site_id,
                "timestamp": timestamp,
                "power_watts": power_watts,
            })

        return repo.upsert_batch(readings)

    async def _sync_power_flow(self, site_id: int) -> None:
        """Sync current power flow snapshot.

        Args:
            site_id: Site ID.
        """
        try:
            flow_data = await self.client.get_power_flow(site_id)

            if not flow_data:
                return

            repo = PowerFlowRepository(self.session)

            # Extract component data
            grid = flow_data.get("GRID", {})
            pv = flow_data.get("PV", {})
            load = flow_data.get("LOAD", {})
            storage = flow_data.get("STORAGE", {})

            db_data = {
                "site_id": site_id,
                "timestamp": datetime.now(),
                "unit": flow_data.get("unit"),
                "grid_status": grid.get("status"),
                "grid_power": grid.get("currentPower"),
                "pv_status": pv.get("status"),
                "pv_power": pv.get("currentPower"),
                "load_status": load.get("status"),
                "load_power": load.get("currentPower"),
                "storage_status": storage.get("status"),
                "storage_power": storage.get("currentPower"),
                "storage_charge_level": storage.get("chargeLevel"),
                "storage_critical": storage.get("critical"),
            }

            repo.upsert(db_data)

        except Exception as e:
            # Power flow is optional, don't fail the sync
            logger.warning("Power flow sync failed", site_id=site_id, error=str(e))
