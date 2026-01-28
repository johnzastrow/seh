"""Environmental benefits repository."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from seh.db.models.environmental import EnvironmentalBenefits
from seh.db.repositories.base import BaseRepository


class EnvironmentalBenefitsRepository(BaseRepository[EnvironmentalBenefits]):
    """Repository for EnvironmentalBenefits operations."""

    model = EnvironmentalBenefits

    def get_by_site_id(self, site_id: int) -> EnvironmentalBenefits | None:
        """Get environmental benefits for a site.

        Args:
            site_id: Site ID.

        Returns:
            EnvironmentalBenefits or None.
        """
        stmt = select(EnvironmentalBenefits).where(
            EnvironmentalBenefits.site_id == site_id
        )
        return self.session.scalar(stmt)

    def upsert(self, data: dict) -> EnvironmentalBenefits:
        """Insert or update environmental benefits.

        Args:
            data: Dictionary of environmental benefits attributes.

        Returns:
            The upserted record.
        """
        dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"

        update_set = {k: v for k, v in data.items() if k != "site_id"}

        if dialect == "postgresql":
            stmt = pg_insert(EnvironmentalBenefits).values(**data)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_environmental_benefits_site",
                set_=update_set,
            )
        else:
            stmt = sqlite_insert(EnvironmentalBenefits).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["site_id"],
                set_=update_set,
            )

        self.session.execute(stmt)
        self.session.flush()

        return self.get_by_site_id(data["site_id"])  # type: ignore
