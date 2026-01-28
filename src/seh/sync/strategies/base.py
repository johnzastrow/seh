"""Base sync strategy."""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta

import structlog
from sqlalchemy.orm import Session

from seh.api.client import SolarEdgeClient
from seh.config.settings import Settings
from seh.db.repositories.sync_metadata import SyncMetadataRepository

logger = structlog.get_logger(__name__)


class BaseSyncStrategy(ABC):
    """Base class for data type sync strategies."""

    data_type: str

    def __init__(
        self,
        client: SolarEdgeClient,
        session: Session,
        settings: Settings,
    ) -> None:
        """Initialize the sync strategy.

        Args:
            client: SolarEdge API client.
            session: Database session.
            settings: Application settings.
        """
        self.client = client
        self.session = session
        self.settings = settings
        self.sync_metadata_repo = SyncMetadataRepository(session)

    def get_last_sync(self, site_id: int) -> datetime | None:
        """Get the last sync timestamp for a site.

        Args:
            site_id: Site ID.

        Returns:
            Last sync timestamp or None if never synced.
        """
        metadata = self.sync_metadata_repo.get_by_site_and_type(site_id, self.data_type)
        if metadata and metadata.last_data_timestamp:
            return metadata.last_data_timestamp
        return None

    def get_start_time(self, site_id: int, lookback_days: int) -> datetime:
        """Get the start time for syncing data.

        Args:
            site_id: Site ID.
            lookback_days: Days to look back for initial sync.

        Returns:
            Start time for sync.
        """
        last_sync = self.get_last_sync(site_id)
        if last_sync:
            # Apply overlap buffer for incremental sync
            return last_sync - timedelta(minutes=self.settings.sync_overlap_minutes)
        else:
            # Initial sync with lookback
            return datetime.now() - timedelta(days=lookback_days)

    def update_sync_metadata(
        self,
        site_id: int,
        last_data_timestamp: datetime | None,
        records_synced: int,
        status: str = "success",
        error_message: str | None = None,
    ) -> None:
        """Update sync metadata after sync completes.

        Args:
            site_id: Site ID.
            last_data_timestamp: Timestamp of latest data synced.
            records_synced: Number of records synced.
            status: Sync status.
            error_message: Error message if failed.
        """
        self.sync_metadata_repo.upsert(
            site_id=site_id,
            data_type=self.data_type,
            last_sync_time=datetime.now(),
            last_data_timestamp=last_data_timestamp,
            records_synced=records_synced,
            status=status,
            error_message=error_message,
        )

    @abstractmethod
    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync data for a site.

        Args:
            site_id: Site ID.
            full: If True, perform full sync ignoring last sync time.

        Returns:
            Number of records synced.
        """
        pass
