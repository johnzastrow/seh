"""Sync orchestrator to coordinate data synchronization."""

from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import Engine

from seh.api.client import SolarEdgeClient
from seh.config.settings import Settings
from seh.db.engine import get_session
from seh.db.repositories.site import SiteRepository
from seh.sync.strategies.alert import AlertSyncStrategy
from seh.sync.strategies.energy import EnergySyncStrategy
from seh.sync.strategies.environmental import EnvironmentalSyncStrategy
from seh.sync.strategies.equipment import EquipmentSyncStrategy
from seh.sync.strategies.inventory import InventorySyncStrategy
from seh.sync.strategies.inverter_telemetry import InverterTelemetrySyncStrategy
from seh.sync.strategies.meter import MeterSyncStrategy
from seh.sync.strategies.power import PowerSyncStrategy
from seh.sync.strategies.site import SiteSyncStrategy
from seh.sync.strategies.storage import StorageSyncStrategy

logger = structlog.get_logger(__name__)


@dataclass
class SyncResult:
    """Result of a sync operation."""

    site_id: int
    site_name: str | None
    success: bool
    records_synced: dict[str, int]
    errors: dict[str, str]
    duration_seconds: float


@dataclass
class SyncSummary:
    """Summary of all sync operations."""

    total_sites: int
    successful_sites: int
    failed_sites: int
    total_records: int
    results: list[SyncResult]
    duration_seconds: float


class SyncOrchestrator:
    """Orchestrates sync operations across all sites and data types."""

    def __init__(
        self,
        client: SolarEdgeClient,
        engine: Engine,
        settings: Settings,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            client: SolarEdge API client.
            engine: SQLAlchemy engine.
            settings: Application settings.
        """
        self.client = client
        self.engine = engine
        self.settings = settings

    async def sync_all(self, full: bool = False) -> SyncSummary:
        """Sync all sites.

        Args:
            full: If True, perform full sync for all data types.

        Returns:
            Summary of sync operations.
        """
        start_time = datetime.now()
        logger.info("Starting sync for all sites", full=full)

        # Get list of sites from API
        sites = await self.client.get_sites()

        if not sites:
            logger.warning("No sites found for this API key")
            return SyncSummary(
                total_sites=0,
                successful_sites=0,
                failed_sites=0,
                total_records=0,
                results=[],
                duration_seconds=0,
            )

        results: list[SyncResult] = []

        for site in sites:
            site_id = site.get("id")
            site_name = site.get("name")

            if not site_id:
                continue

            result = await self.sync_site(site_id, full=full)
            result.site_name = site_name
            results.append(result)

        # Calculate summary
        successful = sum(1 for r in results if r.success)
        total_records = sum(sum(r.records_synced.values()) for r in results)
        duration = (datetime.now() - start_time).total_seconds()

        summary = SyncSummary(
            total_sites=len(results),
            successful_sites=successful,
            failed_sites=len(results) - successful,
            total_records=total_records,
            results=results,
            duration_seconds=duration,
        )

        logger.info(
            "Sync complete",
            sites=summary.total_sites,
            successful=summary.successful_sites,
            records=summary.total_records,
            duration=f"{summary.duration_seconds:.1f}s",
        )

        return summary

    async def sync_site(self, site_id: int, full: bool = False) -> SyncResult:
        """Sync a single site.

        Args:
            site_id: Site ID to sync.
            full: If True, perform full sync for all data types.

        Returns:
            Result of sync operation.
        """
        start_time = datetime.now()
        logger.info("Syncing site", site_id=site_id, full=full)

        records_synced: dict[str, int] = {}
        errors: dict[str, str] = {}

        with get_session(self.engine) as session:
            # Create strategies
            strategies = [
                SiteSyncStrategy(self.client, session, self.settings),
                EquipmentSyncStrategy(self.client, session, self.settings),
                EnergySyncStrategy(self.client, session, self.settings),
                PowerSyncStrategy(self.client, session, self.settings),
                StorageSyncStrategy(self.client, session, self.settings),
                MeterSyncStrategy(self.client, session, self.settings),
                EnvironmentalSyncStrategy(self.client, session, self.settings),
                AlertSyncStrategy(self.client, session, self.settings),
                InventorySyncStrategy(self.client, session, self.settings),
                InverterTelemetrySyncStrategy(self.client, session, self.settings),
            ]

            # Run each strategy
            for strategy in strategies:
                try:
                    count = await strategy.sync(site_id, full=full)
                    records_synced[strategy.data_type] = count
                except Exception as e:
                    logger.error(
                        "Strategy sync failed",
                        site_id=site_id,
                        data_type=strategy.data_type,
                        error=str(e),
                    )
                    errors[strategy.data_type] = str(e)
                    records_synced[strategy.data_type] = 0

        duration = (datetime.now() - start_time).total_seconds()

        return SyncResult(
            site_id=site_id,
            site_name=None,
            success=len(errors) == 0,
            records_synced=records_synced,
            errors=errors,
            duration_seconds=duration,
        )

    async def get_sites(self) -> list[dict]:
        """Get list of sites from API.

        Returns:
            List of site dictionaries.
        """
        return await self.client.get_sites()

    def get_sync_status(self) -> list[dict]:
        """Get sync status for all sites.

        Returns:
            List of sync status dictionaries.
        """
        with get_session(self.engine) as session:
            site_repo = SiteRepository(session)
            sites = site_repo.get_all()

            statuses = []
            for site in sites:
                status = {
                    "site_id": site.id,
                    "site_name": site.name,
                    "last_update": site.updated_at,
                    "data_types": {},
                }

                for metadata in site.sync_metadata:
                    status["data_types"][metadata.data_type] = {
                        "last_sync": metadata.last_sync_time,
                        "last_data": metadata.last_data_timestamp,
                        "records": metadata.records_synced,
                        "status": metadata.status,
                        "error": metadata.error_message,
                    }

                statuses.append(status)

            return statuses
