"""Site sync strategy."""

import contextlib
from datetime import datetime

import structlog

from seh.db.repositories.site import SiteRepository
from seh.sync.strategies.base import BaseSyncStrategy

logger = structlog.get_logger(__name__)


class SiteSyncStrategy(BaseSyncStrategy):
    """Sync strategy for site data."""

    data_type = "site"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync site details.

        Args:
            site_id: Site ID.
            full: Ignored for site sync (always fetches latest).

        Returns:
            Number of records synced (0 or 1).
        """
        logger.info("Syncing site details", site_id=site_id)

        try:
            site_data = await self.client.get_site_details(site_id)

            if not site_data:
                logger.warning("No site data returned", site_id=site_id)
                self.update_sync_metadata(site_id, None, 0, "error", "No data returned")
                return 0

            # Transform API response to database model
            location = site_data.get("location", {})
            primary_module = site_data.get("primaryModule", {})
            public_settings = site_data.get("publicSettings", {})

            db_data = {
                "id": site_id,
                "name": site_data.get("name"),
                "account_id": site_data.get("accountId"),
                "status": site_data.get("status"),
                "peak_power": site_data.get("peakPower"),
                "currency": site_data.get("currency"),
                "notes": site_data.get("notes"),
                "site_type": site_data.get("type"),
                "country": location.get("country"),
                "state": location.get("state"),
                "city": location.get("city"),
                "address": location.get("address"),
                "address2": location.get("address2"),
                "zip_code": location.get("zip"),
                "timezone": location.get("timeZone"),
                "primary_module_manufacturer": primary_module.get("manufacturerName"),
                "primary_module_model": primary_module.get("modelName"),
                "primary_module_power": primary_module.get("maximumPower"),
                "is_public": public_settings.get("isPublic"),
                "public_name": public_settings.get("name"),
            }

            # Parse dates
            if site_data.get("lastUpdateTime"):
                with contextlib.suppress(ValueError, AttributeError):
                    db_data["last_update_time"] = datetime.fromisoformat(
                        site_data["lastUpdateTime"].replace("Z", "+00:00")
                    )

            if site_data.get("installationDate"):
                with contextlib.suppress(ValueError, AttributeError):
                    db_data["installation_date"] = datetime.strptime(
                        site_data["installationDate"], "%Y-%m-%d"
                    )

            # Upsert site
            repo = SiteRepository(self.session)
            repo.upsert(db_data)

            self.update_sync_metadata(site_id, datetime.now(), 1)
            logger.info("Site sync complete", site_id=site_id)
            return 1

        except Exception as e:
            logger.error("Site sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
