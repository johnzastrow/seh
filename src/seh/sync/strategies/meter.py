"""Meter sync strategy."""

from datetime import datetime, timedelta

import structlog

from seh.db.repositories.meter import MeterReadingRepository, MeterRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.utils.exceptions import APIError

logger = structlog.get_logger(__name__)


class MeterSyncStrategy(BaseSyncStrategy):
    """Sync strategy for meter data."""

    data_type = "meter"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync meter data.

        Args:
            site_id: Site ID.
            full: If True, sync from lookback date regardless of last sync.

        Returns:
            Number of records synced.
        """
        logger.info("Syncing meter data", site_id=site_id, full=full)

        try:
            # First sync meter list
            try:
                meters = await self.client.get_meters(site_id)
            except APIError as e:
                # 400 errors typically mean no meters or feature not available
                if e.status_code == 400:
                    logger.info("Meters not available for site", site_id=site_id)
                    self.update_sync_metadata(site_id, datetime.now(), 0)
                    return 0
                raise

            if not meters:
                logger.info("No meters found", site_id=site_id)
                self.update_sync_metadata(site_id, datetime.now(), 0)
                return 0

            meter_repo = MeterRepository(self.session)
            meter_map: dict[str, int] = {}

            for meter_data in meters:
                name = meter_data.get("name")
                if not name:
                    continue

                db_data = {
                    "site_id": site_id,
                    "name": name,
                    "manufacturer": meter_data.get("manufacturer"),
                    "model": meter_data.get("model"),
                    "meter_type": meter_data.get("type"),
                    "serial_number": meter_data.get("SN"),
                    "connection_type": meter_data.get("connectedTo"),
                    "form": meter_data.get("form"),
                }

                meter = meter_repo.upsert(db_data)
                meter_map[name] = meter.id

            # Determine time range for readings
            end_time = datetime.now()

            if full:
                start_time = end_time - timedelta(days=self.settings.power_lookback_days)
            else:
                start_time = self.get_start_time(site_id, self.settings.power_lookback_days)

            # Fetch meter readings
            meter_data = await self.client.get_meter_data(
                site_id=site_id,
                start_time=start_time,
                end_time=end_time,
            )

            if not meter_data:
                logger.info("No meter readings found", site_id=site_id)
                self.update_sync_metadata(site_id, datetime.now(), len(meters))
                return len(meters)

            # Process meter readings
            reading_repo = MeterReadingRepository(self.session)
            total_count = len(meters)
            latest_timestamp: datetime | None = None

            # Meter data structure varies, handle both formats
            meter_readings = meter_data.get("meters", [])
            if not meter_readings:
                # Try alternate structure
                for meter_name in meter_data.get("meterSerialNumber", {}):
                    meter_readings.append({
                        "name": meter_name,
                        "values": meter_data.get("meterSerialNumber", {}).get(meter_name, []),
                    })

            for meter_info in meter_readings:
                meter_name = meter_info.get("name", meter_info.get("meterSerialNumber"))
                meter_id = meter_map.get(meter_name)

                if not meter_id:
                    continue

                values = meter_info.get("values", [])
                readings = []

                for value in values:
                    date_str = value.get("date")
                    if not date_str:
                        continue

                    try:
                        timestamp = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        try:
                            timestamp = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        except ValueError:
                            continue

                    reading = {
                        "meter_id": meter_id,
                        "timestamp": timestamp,
                    }

                    # Extract values from nested structure
                    vals = value.get("values", value)
                    reading["power"] = vals.get("power")
                    reading["energy_lifetime"] = vals.get("energy")
                    reading["voltage_l1"] = vals.get("voltage", {}).get("L1")
                    reading["voltage_l2"] = vals.get("voltage", {}).get("L2")
                    reading["voltage_l3"] = vals.get("voltage", {}).get("L3")
                    reading["current_l1"] = vals.get("current", {}).get("L1")
                    reading["current_l2"] = vals.get("current", {}).get("L2")
                    reading["current_l3"] = vals.get("current", {}).get("L3")
                    reading["power_factor"] = vals.get("powerFactor")

                    readings.append(reading)

                    if latest_timestamp is None or timestamp > latest_timestamp:
                        latest_timestamp = timestamp

                count = reading_repo.upsert_batch(readings)
                total_count += count

            self.update_sync_metadata(site_id, latest_timestamp, total_count)
            logger.info("Meter sync complete", site_id=site_id, count=total_count)
            return total_count

        except Exception as e:
            logger.error("Meter sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
