"""Sync metadata repository."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from seh.db.models.sync_metadata import SyncMetadata
from seh.db.repositories.base import BaseRepository


class SyncMetadataRepository(BaseRepository[SyncMetadata]):
    """Repository for SyncMetadata operations."""

    model = SyncMetadata

    def get_by_site_and_type(self, site_id: int, data_type: str) -> SyncMetadata | None:
        """Get sync metadata for a specific site and data type.

        Args:
            site_id: Site ID.
            data_type: Data type (site, equipment, energy, power, storage, meter).

        Returns:
            SyncMetadata or None.
        """
        stmt = select(SyncMetadata).where(
            SyncMetadata.site_id == site_id,
            SyncMetadata.data_type == data_type,
        )
        return self.session.scalar(stmt)

    def get_by_site(self, site_id: int) -> list[SyncMetadata]:
        """Get all sync metadata for a site.

        Args:
            site_id: Site ID.

        Returns:
            List of sync metadata entries.
        """
        stmt = select(SyncMetadata).where(SyncMetadata.site_id == site_id)
        return list(self.session.scalars(stmt).all())

    def upsert(
        self,
        site_id: int,
        data_type: str,
        last_sync_time: datetime,
        last_data_timestamp: datetime | None = None,
        records_synced: int | None = None,
        status: str = "success",
        error_message: str | None = None,
    ) -> SyncMetadata:
        """Insert or update sync metadata.

        Args:
            site_id: Site ID.
            data_type: Data type.
            last_sync_time: When the sync completed.
            last_data_timestamp: Timestamp of the latest data synced.
            records_synced: Number of records synced.
            status: Sync status (success, partial, error).
            error_message: Error message if status is error.

        Returns:
            The upserted sync metadata.
        """
        data = {
            "site_id": site_id,
            "data_type": data_type,
            "last_sync_time": last_sync_time,
            "last_data_timestamp": last_data_timestamp,
            "records_synced": records_synced,
            "status": status,
            "error_message": error_message,
        }

        dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"

        update_set = {k: v for k, v in data.items() if k not in ("site_id", "data_type")}

        if dialect == "postgresql":
            stmt = pg_insert(SyncMetadata).values(**data)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_sync_metadata",
                set_=update_set,
            )
        elif dialect in ("mysql", "mariadb"):
            stmt = mysql_insert(SyncMetadata).values(**data)
            stmt = stmt.on_duplicate_key_update(**update_set)
        else:
            stmt = sqlite_insert(SyncMetadata).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["site_id", "data_type"],
                set_=update_set,
            )

        self.session.execute(stmt)
        self.session.flush()

        return self.get_by_site_and_type(site_id, data_type)  # type: ignore
