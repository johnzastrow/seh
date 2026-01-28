"""Alert sync strategy."""

import contextlib
from datetime import datetime

import structlog

from seh.db.repositories.alert import AlertRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.utils.exceptions import APIError

logger = structlog.get_logger(__name__)


class AlertSyncStrategy(BaseSyncStrategy):
    """Sync strategy for alert data."""

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

            if not alerts:
                logger.info("No alerts for site", site_id=site_id)
                self.update_sync_metadata(site_id, datetime.now(), 0)
                return 0

            repo = AlertRepository(self.session)
            synced = 0
            latest_timestamp = None

            for alert in alerts:
                alert_id = alert.get("alertId")
                if not alert_id:
                    continue

                # Parse timestamp
                alert_timestamp = None
                if alert.get("alertTimestamp"):
                    with contextlib.suppress(ValueError, AttributeError):
                        alert_timestamp = datetime.fromisoformat(
                            alert["alertTimestamp"].replace("Z", "+00:00")
                        )

                db_data = {
                    "site_id": site_id,
                    "alert_id": alert_id,
                    "severity": alert.get("severity"),
                    "alert_code": alert.get("alertCode"),
                    "alert_type": alert.get("alertType"),
                    "name": alert.get("componentName"),
                    "description": alert.get("message"),
                    "serial_number": alert.get("componentSerialNumber"),
                    "alert_timestamp": alert_timestamp,
                }

                repo.upsert(db_data)
                synced += 1

                if alert_timestamp and (
                    latest_timestamp is None or alert_timestamp > latest_timestamp
                ):
                    latest_timestamp = alert_timestamp

            self.update_sync_metadata(site_id, latest_timestamp or datetime.now(), synced)
            logger.info("Alert sync complete", site_id=site_id, alerts_synced=synced)
            return synced

        except APIError as e:
            if e.status_code in (400, 403):
                logger.info(
                    "Alerts not available for site",
                    site_id=site_id,
                    reason="forbidden" if e.status_code == 403 else "not_supported",
                )
                self.update_sync_metadata(site_id, datetime.now(), 0)
                return 0
            raise
        except Exception as e:
            logger.error("Alert sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
