"""Energy sync strategy."""

from datetime import date, datetime, timedelta

import structlog

from seh.db.repositories.energy import EnergyRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.sync.v2_fields import site_local

logger = structlog.get_logger(__name__)


class EnergySyncStrategy(BaseSyncStrategy):
    """Sync strategy for daily energy (GET /sites/{id}/energy, resolution DAY, Wh)."""

    data_type = "energy"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync daily energy production.

        The client splits the range into SolarEdge's maximum DAY window (one month).
        Today's value is partial and is updated on the next sync.

        Args:
            site_id: Site ID.
            full: If True, sync from lookback date regardless of last sync.

        Returns:
            Number of records synced.
        """
        logger.info("Syncing energy data", site_id=site_id, full=full)

        try:
            today = date.today()
            if full:
                start_date = today - timedelta(days=self.settings.energy_lookback_days)
            else:
                start_date = self.get_start_time(site_id, self.settings.energy_lookback_days).date()

            # The range end is exclusive, so end at tomorrow's midnight to include today.
            values = await self.client.get_energy(
                site_id, start_date, today + timedelta(days=1), resolution="DAY"
            )

            readings = []
            latest_date: date | None = None
            for value in values:
                timestamp = site_local(value.get("timestamp"))
                energy_wh = value.get("value")
                if timestamp is None or energy_wh is None:
                    continue
                reading_date = timestamp.date()
                readings.append(
                    {
                        "site_id": site_id,
                        "reading_date": reading_date,
                        "time_unit": "DAY",
                        "energy_wh": energy_wh,
                    }
                )
                if latest_date is None or reading_date > latest_date:
                    latest_date = reading_date

            count = EnergyRepository(self.session).upsert_batch(readings) if readings else 0
            if not readings:
                logger.info("No energy data found", site_id=site_id)

            last_timestamp = (
                datetime.combine(latest_date, datetime.min.time()) if latest_date else None
            )
            self.update_sync_metadata(site_id, last_timestamp, count)
            logger.info("Energy sync complete", site_id=site_id, count=count)
            return count

        except Exception as e:
            logger.error("Energy sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
