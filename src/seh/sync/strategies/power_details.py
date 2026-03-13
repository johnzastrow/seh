"""Power details sync strategy.

Fetches the SolarEdge powerDetails endpoint which provides a 15-minute
historical time series of five power meter types:
  - Production     : PV output (W)
  - Consumption    : Total home load (W)
  - SelfConsumption: Solar power used on-site (W)
  - FeedIn         : Power exported to grid (W)
  - Purchased      : Power imported from grid (W)

All values are stored in Watts in seh_power_details.  The chart layer
converts to kW as needed.
"""

from datetime import datetime, timedelta

import structlog

from seh.db.repositories.power import PowerDetailsRepository
from seh.sync.strategies.base import BaseSyncStrategy

logger = structlog.get_logger(__name__)

# Map API meter type strings to table column names
METER_TYPE_TO_COL = {
    "Production": "production_w",
    "Consumption": "consumption_w",
    "SelfConsumption": "self_consumption_w",
    "FeedIn": "feed_in_w",
    "Purchased": "purchased_w",
}


class PowerDetailsSyncStrategy(BaseSyncStrategy):
    """Sync strategy for detailed power breakdown data."""

    data_type = "power_details"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync detailed power breakdown from the powerDetails API.

        Args:
            site_id: Site ID.
            full: If True, sync from lookback date regardless of last sync.

        Returns:
            Number of records synced.
        """
        logger.info("Syncing power details data", site_id=site_id, full=full)

        try:
            end_time = datetime.now()

            if full:
                start_time = end_time - timedelta(days=self.settings.power_details_lookback_days)
            else:
                start_time = self.get_start_time(site_id, self.settings.power_details_lookback_days)

            # powerDetails API is limited to 1 month per request
            total_count = 0
            current_start = start_time
            latest_timestamp: datetime | None = None

            while current_start < end_time:
                chunk_end = min(current_start + timedelta(days=25), end_time)
                chunk_count, chunk_latest = await self._sync_chunk(site_id, current_start, chunk_end)
                total_count += chunk_count
                if chunk_latest and (latest_timestamp is None or chunk_latest > latest_timestamp):
                    latest_timestamp = chunk_latest
                current_start = chunk_end

            self.update_sync_metadata(site_id, latest_timestamp, total_count)
            logger.info("Power details sync complete", site_id=site_id, count=total_count)
            return total_count

        except Exception as e:
            logger.error("Power details sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise

    async def _sync_chunk(
        self,
        site_id: int,
        start_time: datetime,
        end_time: datetime,
    ) -> tuple[int, datetime | None]:
        """Fetch and store one chunk of powerDetails data (≤30 days).

        Returns:
            Tuple of (records_upserted, latest_timestamp).
        """
        power_details = await self.client.get_power_details(
            site_id=site_id,
            start_time=start_time,
            end_time=end_time,
        )

        if not power_details:
            return 0, None

        meters = power_details.get("meters", [])
        if not meters:
            return 0, None

        # Build a dict keyed by timestamp so all meter types land in the same row
        rows: dict[datetime, dict] = {}

        for meter in meters:
            meter_type = meter.get("type", "")
            col = METER_TYPE_TO_COL.get(meter_type)
            if col is None:
                logger.debug("Unknown meter type, skipping", meter_type=meter_type)
                continue

            for value in meter.get("values", []):
                date_str = value.get("date")
                if not date_str:
                    continue

                try:
                    ts = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    try:
                        ts = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    except ValueError:
                        logger.warning("Unparseable timestamp", raw=date_str)
                        continue

                if ts not in rows:
                    rows[ts] = {"site_id": site_id, "timestamp": ts}

                rows[ts][col] = value.get("value")

        if not rows:
            return 0, None

        repo = PowerDetailsRepository(self.session)
        count = repo.upsert_batch(list(rows.values()))
        latest = max(rows.keys())
        return count, latest
