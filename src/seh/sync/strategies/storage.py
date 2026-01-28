"""Storage (battery) sync strategy."""

from datetime import datetime, timedelta

import structlog

from seh.db.repositories.battery import BatteryRepository
from seh.sync.strategies.base import BaseSyncStrategy

logger = structlog.get_logger(__name__)


class StorageSyncStrategy(BaseSyncStrategy):
    """Sync strategy for storage/battery data."""

    data_type = "storage"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync storage/battery data.

        Args:
            site_id: Site ID.
            full: If True, sync from lookback date regardless of last sync.

        Returns:
            Number of records synced.
        """
        logger.info("Syncing storage data", site_id=site_id, full=full)

        try:
            # Determine time range
            end_time = datetime.now()

            if full:
                start_time = end_time - timedelta(days=self.settings.power_lookback_days)
            else:
                start_time = self.get_start_time(site_id, self.settings.power_lookback_days)

            # Fetch storage data
            storage_data = await self.client.get_storage_data(
                site_id=site_id,
                start_time=start_time,
                end_time=end_time,
            )

            if not storage_data:
                logger.info("No storage data found", site_id=site_id)
                self.update_sync_metadata(site_id, datetime.now(), 0)
                return 0

            batteries = storage_data.get("batteries", [])
            if not batteries:
                logger.info("No batteries found", site_id=site_id)
                self.update_sync_metadata(site_id, datetime.now(), 0)
                return 0

            repo = BatteryRepository(self.session)
            count = 0
            latest_timestamp: datetime | None = None

            for battery in batteries:
                serial = battery.get("serialNumber")
                if not serial:
                    continue

                # Get latest telemetry
                telemetries = battery.get("telemetries", [])
                latest_telemetry = telemetries[-1] if telemetries else {}

                db_data = {
                    "site_id": site_id,
                    "serial_number": serial,
                    "name": battery.get("name"),
                    "manufacturer": battery.get("manufacturerName"),
                    "model": battery.get("modelNumber"),
                    "nameplate_capacity": battery.get("nameplate"),
                    "connected_inverter_sn": battery.get("connectedInverterSn"),
                }

                # Add telemetry snapshot
                if latest_telemetry:
                    db_data["last_power"] = latest_telemetry.get("power")
                    db_data["last_status"] = latest_telemetry.get("batteryState")
                    db_data["last_state_of_charge"] = latest_telemetry.get("batteryPercentageState")
                    db_data["lifetime_energy_charged"] = latest_telemetry.get("lifeTimeEnergyCharged")
                    db_data["lifetime_energy_discharged"] = latest_telemetry.get("lifeTimeEnergyDischarged")
                    db_data["capacity"] = latest_telemetry.get("fullPackEnergyAvailable")

                    ts_str = latest_telemetry.get("timeStamp")
                    if ts_str:
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            db_data["last_telemetry_time"] = ts
                            if latest_timestamp is None or ts > latest_timestamp:
                                latest_timestamp = ts
                        except ValueError:
                            pass

                repo.upsert(db_data)
                count += 1

            self.update_sync_metadata(site_id, latest_timestamp, count)
            logger.info("Storage sync complete", site_id=site_id, count=count)
            return count

        except Exception as e:
            logger.error("Storage sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
