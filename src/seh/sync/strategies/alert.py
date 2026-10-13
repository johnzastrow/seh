"""Alert sync strategy."""

from datetime import datetime
from typing import Any

import structlog

from seh.db.repositories.alert import AlertRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.sync.v2_fields import site_local

logger = structlog.get_logger(__name__)

# The V2 alert schema has not been observed live (the verified site had no alerts).
# Field names follow a community V2 client; timestamps are taken from the first of
# these fields present.
TIMESTAMP_FIELDS = ("openedAt", "firstOccurrence", "createdAt", "timestamp", "alertTimestamp")


class AlertSyncStrategy(BaseSyncStrategy):
    """Sync strategy for alerts (GET /sites/{id}/alerts)."""

    data_type = "alert"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync alerts for a site.

        Args:
            site_id: Site ID.
            full: Ignored for alert sync (always fetches all alerts).

        Returns:
            Number of records synced.
        """
        logger.info("Syncing alerts", site_id=site_id)

        try:
            alerts = await self.client.get_alerts(site_id)

            repo = AlertRepository(self.session)
            synced = 0
            latest_timestamp = None

            for alert in alerts:
                try:
                    alert_id = int(alert.get("alertId"))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    continue

                component: dict[str, Any] = alert.get("component") or {}
                alert_timestamp = next(
                    (ts for f in TIMESTAMP_FIELDS if (ts := site_local(alert.get(f)))), None
                )
                impact = alert.get("impact")

                db_data: dict[str, Any] = {
                    "site_id": site_id,
                    "alert_id": alert_id,
                    "severity": str(impact) if impact is not None else None,
                    "alert_type": alert.get("type"),
                    "name": component.get("name") or alert.get("category"),
                    "description": alert.get("description") or alert.get("category"),
                    "serial_number": component.get("serialNumber"),
                    "alert_timestamp": alert_timestamp,
                }
                repo.upsert(db_data)
                synced += 1

                if alert_timestamp and (
                    latest_timestamp is None or alert_timestamp > latest_timestamp
                ):
                    latest_timestamp = alert_timestamp

            if not alerts:
                logger.info("No alerts for site", site_id=site_id)
            self.update_sync_metadata(site_id, latest_timestamp or datetime.now(), synced)
            logger.info("Alert sync complete", site_id=site_id, alerts_synced=synced)
            return synced

        except Exception as e:
            if self.skip_if_unavailable(site_id, e):
                return 0
            logger.error("Alert sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
