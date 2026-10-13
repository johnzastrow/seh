"""Environmental benefits sync strategy."""

from datetime import datetime
from typing import Any

import structlog

from seh.db.repositories.environmental import EnvironmentalBenefitsRepository
from seh.sync.strategies.base import BaseSyncStrategy

logger = structlog.get_logger(__name__)

# V2 reports a unit system instead of V1's mass unit.
CO2_UNITS = {"METRIC": "KG", "IMPERIAL": "LB"}


class EnvironmentalSyncStrategy(BaseSyncStrategy):
    """Sync strategy for environmental benefits (GET /sites/{id}/environmental-benefits)."""

    data_type = "environmental"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync environmental benefits for a site.

        V2 reports only CO2 avoided (and EV miles, which has no column). Trees planted,
        light bulbs, SO2, and NOx keep their last V1 values.

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

            unit = env_data.get("unit")
            db_data: dict[str, Any] = {
                "site_id": site_id,
                "co2_saved": env_data.get("co2Emissions"),
                "co2_units": CO2_UNITS.get(str(unit).upper(), unit) if unit else None,
            }

            EnvironmentalBenefitsRepository(self.session).upsert(db_data)

            self.update_sync_metadata(site_id, datetime.now(), 1)
            logger.info("Environmental benefits sync complete", site_id=site_id)
            return 1

        except Exception as e:
            if self.skip_if_unavailable(site_id, e):
                return 0
            logger.error("Environmental sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
