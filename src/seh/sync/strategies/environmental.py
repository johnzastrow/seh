"""Environmental benefits sync strategy."""

from datetime import datetime

import structlog

from seh.db.repositories.environmental import EnvironmentalBenefitsRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.utils.exceptions import APIError

logger = structlog.get_logger(__name__)


class EnvironmentalSyncStrategy(BaseSyncStrategy):
    """Sync strategy for environmental benefits data."""

    data_type = "environmental"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync environmental benefits for a site.

        Args:
            site_id: Site ID.
            full: Ignored for environmental sync (always fetches latest).

        Returns:
            Number of records synced (0 or 1).
        """
        logger.info("Syncing environmental benefits", site_id=site_id)

        try:
            env_data = await self.client.get_environmental_benefits(site_id)

            if not env_data:
                logger.warning("No environmental benefits returned", site_id=site_id)
                self.update_sync_metadata(site_id, None, 0, "error", "No data returned")
                return 0

            # Transform API response to database model
            gas_emission = env_data.get("gasEmissionSaved", {})
            db_data = {
                "site_id": site_id,
                "trees_planted": env_data.get("treesPlanted"),
                "light_bulbs": env_data.get("lightBulbs"),
                "co2_saved": gas_emission.get("co2"),
                "so2_saved": gas_emission.get("so2"),
                "nox_saved": gas_emission.get("nox"),
                "co2_units": gas_emission.get("units"),
            }

            # Upsert environmental benefits
            repo = EnvironmentalBenefitsRepository(self.session)
            repo.upsert(db_data)

            self.update_sync_metadata(site_id, datetime.now(), 1)
            logger.info("Environmental benefits sync complete", site_id=site_id)
            return 1

        except APIError as e:
            if e.status_code == 400:
                logger.info("Environmental benefits not available", site_id=site_id)
                self.update_sync_metadata(site_id, datetime.now(), 0)
                return 0
            raise
        except Exception as e:
            logger.error("Environmental sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
