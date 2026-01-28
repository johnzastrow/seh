"""Site repository."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from seh.db.models.site import Site
from seh.db.repositories.base import BaseRepository


class SiteRepository(BaseRepository[Site]):
    """Repository for Site operations."""

    model = Site

    def get_all_site_ids(self) -> list[int]:
        """Get all site IDs.

        Returns:
            List of site IDs.
        """
        stmt = select(Site.id)
        return list(self.session.scalars(stmt).all())

    def upsert(self, site_data: dict) -> Site:
        """Insert or update a site.

        Args:
            site_data: Dictionary of site attributes.

        Returns:
            The upserted site.
        """
        # Determine dialect and use appropriate insert
        dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"

        if dialect == "postgresql":
            stmt = pg_insert(Site).values(**site_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={k: v for k, v in site_data.items() if k != "id"},
            )
        else:
            # SQLite and MariaDB
            stmt = sqlite_insert(Site).values(**site_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={k: v for k, v in site_data.items() if k != "id"},
            )

        self.session.execute(stmt)
        self.session.flush()

        # Return the site
        return self.get_by_id(site_data["id"])  # type: ignore
