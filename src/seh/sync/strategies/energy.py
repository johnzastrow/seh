"""Energy sync strategy."""

from datetime import date, datetime, timedelta

import structlog

from seh.db.repositories.energy import EnergyRepository
from seh.sync.strategies.base import BaseSyncStrategy

logger = structlog.get_logger(__name__)


class EnergySyncStrategy(BaseSyncStrategy):
    """Sync strategy for energy data."""

    data_type = "energy"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync energy production data.

        Args:
            site_id: Site ID.
            full: If True, sync from lookback date regardless of last sync.

        Returns:
            Number of records synced.
        """
        logger.info("Syncing energy data", site_id=site_id, full=full)

        try:
            # Determine date range
            end_date = date.today()

            if full:
                start_date = end_date - timedelta(days=self.settings.energy_lookback_days)
            else:
                start_time = self.get_start_time(site_id, self.settings.energy_lookback_days)
                start_date = start_time.date()

            # Fetch energy data
            energy_values = await self.client.get_energy(
                site_id=site_id,
                start_date=start_date,
                end_date=end_date,
                time_unit="DAY",
            )

            if not energy_values:
                logger.info("No energy data found", site_id=site_id)
                self.update_sync_metadata(site_id, datetime.now(), 0)
                return 0

            # Transform to database records
            repo = EnergyRepository(self.session)
            readings = []
            latest_date: date | None = None

            for value in energy_values:
                date_str = value.get("date")
                if not date_str:
                    continue

                try:
                    reading_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                except ValueError:
                    logger.warning("Invalid date format", date=date_str)
                    continue

                energy_wh = value.get("value")
                if energy_wh is None:
                    continue

                readings.append({
                    "site_id": site_id,
                    "reading_date": reading_date,
                    "time_unit": "DAY",
                    "energy_wh": energy_wh,
                })

                if latest_date is None or reading_date > latest_date:
                    latest_date = reading_date

            # Upsert all readings
            count = repo.upsert_batch(readings)

            last_timestamp = datetime.combine(latest_date, datetime.min.time()) if latest_date else None
            self.update_sync_metadata(site_id, last_timestamp, count)
            logger.info("Energy sync complete", site_id=site_id, count=count)
            return count

        except Exception as e:
            logger.error("Energy sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
