"""Site sync strategy."""

from datetime import datetime
from typing import Any

import structlog

from seh.db.repositories.site import SiteRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.sync.v2_fields import calendar_date, title_case, utc_to_site_local

logger = structlog.get_logger(__name__)


class SiteSyncStrategy(BaseSyncStrategy):
    """Sync strategy for site data (GET /sites/{id})."""

    data_type = "site"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync site details.

        V2 no longer reports currency, site type, primary module, or public settings;
        those columns keep their last V1 values.

        Args:
            site_id: Site ID.
            full: Ignored for site sync (always fetches latest).

        Returns:
            Number of records synced (0 or 1).
        """
        logger.info("Syncing site details", site_id=site_id)

        try:
            site_data = await self.client.get_site(site_id)

            if not site_data:
                logger.warning("No site data returned", site_id=site_id)
                self.update_sync_metadata(site_id, None, 0, "error", "No data returned")
                return 0

            location: dict[str, Any] = site_data.get("location") or {}
            timezone_name = location.get("timezone")

            db_data: dict[str, Any] = {
                "id": site_id,
                "name": site_data.get("name") or f"Site {site_id}",
                "account_id": site_data.get("accountId"),
                "status": title_case(site_data.get("activationStatus")),
                "peak_power": site_data.get("peakPower"),
                "notes": site_data.get("note"),
                "country": location.get("country"),
                "state": location.get("state"),
                "city": location.get("city"),
                "address": location.get("address"),
                "address2": location.get("address2"),
                "zip_code": location.get("zip"),
                "timezone": timezone_name,
                "last_update_time": utc_to_site_local(
                    site_data.get("lastUpdateTime"), timezone_name
                ),
                "installation_date": calendar_date(site_data.get("installationDate")),
            }

            SiteRepository(self.session).upsert(db_data)

            self.update_sync_metadata(site_id, datetime.now(), 1)
            logger.info("Site sync complete", site_id=site_id)
            return 1

        except Exception as e:
            logger.error("Site sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
