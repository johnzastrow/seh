"""Optimizer telemetry sync strategy (not available in API V2)."""

import structlog

from seh.sync.strategies.base import BaseSyncStrategy

logger = structlog.get_logger(__name__)


class OptimizerTelemetrySyncStrategy(BaseSyncStrategy):
    """Placeholder: SolarEdge API V2 has no optimizer telemetry endpoint.

    Optimizers are listed by the inventory strategy, but no per-panel data can be
    fetched (/equipment/{serial}/telemetry returns 404 "Unknown endpoint"). The V1
    implementation never stored rows either. The data type is kept so existing
    SEH_SKIP_DATA_TYPES values stay valid; it makes no API calls.
    """

    data_type = "optimizer_telemetry"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Record a skip without calling the API.

        Args:
            site_id: Site ID.
            full: Ignored.

        Returns:
            Always 0.
        """
        logger.debug("Optimizer telemetry is not available in SolarEdge API V2", site_id=site_id)
        self.update_sync_metadata(site_id, None, 0, "skipped", "Not available in SolarEdge API V2")
        return 0
