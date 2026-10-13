"""Power details sync strategy.

Builds the 15-minute power breakdown in seh_power_details from V2 meter telemetry
(GET /sites/{id}/meters/telemetry, QUARTER_HOUR). V2 has no powerDetails endpoint; the
meters report production, grid import, and grid export, and the other two V1 series are
derived from them:

  - production_w       = productionPower
  - purchased_w        = importPower                (from grid)
  - feed_in_w          = exportPower                (to grid)
  - consumption_w      = production + import - export
  - self_consumption_w = production - export

All values are 15-minute averages in watts, as in V1.
"""

from datetime import datetime, timedelta
from typing import Any

import structlog

from seh.db.repositories.power import PowerDetailsRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.sync.v2_fields import site_local

logger = structlog.get_logger(__name__)

METRICS = {"productionPower": "production", "importPower": "import", "exportPower": "export"}


def derive_row(values: dict[str, float]) -> dict[str, float | None]:
    """Turn measured production/import/export into the five V1 power-details columns.

    A derived value is only computed when all of its inputs were measured, so a gap in
    one meter series yields NULL rather than a misleading number.
    """
    production = values.get("production")
    imported = values.get("import")
    exported = values.get("export")
    consumption = None
    if production is not None and imported is not None and exported is not None:
        consumption = production + imported - exported
    self_consumption = None
    if production is not None and exported is not None:
        self_consumption = production - exported
    return {
        "production_w": production,
        "purchased_w": imported,
        "feed_in_w": exported,
        "consumption_w": consumption,
        "self_consumption_w": self_consumption,
    }


class PowerDetailsSyncStrategy(BaseSyncStrategy):
    """Sync strategy for the 15-minute power breakdown."""

    data_type = "power_details"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync the power breakdown from meter telemetry.

        Args:
            site_id: Site ID.
            full: If True, sync from lookback date regardless of last sync.

        Returns:
            Number of records synced.
        """
        logger.info("Syncing power details data", site_id=site_id, full=full)

        try:
            end_time = datetime.now()
            lookback = self.settings.power_details_lookback_days
            if full:
                start_time = end_time - timedelta(days=lookback)
            else:
                start_time = self.get_start_time(site_id, lookback)

            meters = await self.client.get_meters_telemetry(
                site_id, start_time, end_time, resolution="QUARTER_HOUR"
            )

            # Sum each metric across meters per interval (a site normally has one meter
            # reporting each direction; summing also covers split installations).
            measured: dict[datetime, dict[str, float]] = {}
            for metrics in meters.values():
                for metric, key in METRICS.items():
                    series: dict[str, Any] = metrics.get(metric) or {}
                    for point in series.get("values") or []:
                        timestamp = site_local(point.get("timestamp"))
                        value = point.get("value")
                        if timestamp is None or value is None:
                            continue
                        row = measured.setdefault(timestamp, {})
                        row[key] = row.get(key, 0.0) + float(value)

            readings = [
                {"site_id": site_id, "timestamp": ts, **derive_row(values)}
                for ts, values in sorted(measured.items())
            ]
            count = PowerDetailsRepository(self.session).upsert_batch(readings) if readings else 0
            latest = max(measured) if measured else None

            if not meters:
                logger.info("No meter telemetry returned", site_id=site_id)
            self.update_sync_metadata(site_id, latest, count)
            logger.info("Power details sync complete", site_id=site_id, count=count)
            return count

        except Exception as e:
            if self.skip_if_unavailable(site_id, e):
                return 0
            logger.error("Power details sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
