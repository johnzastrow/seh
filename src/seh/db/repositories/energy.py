"""Energy reading repository."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from seh.db.models.energy import EnergyReading
from seh.db.repositories.base import BaseRepository


class EnergyRepository(BaseRepository[EnergyReading]):
    """Repository for EnergyReading operations."""

    model = EnergyReading

    def get_by_site_id(
        self,
        site_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
        time_unit: str = "DAY",
    ) -> list[EnergyReading]:
        """Get energy readings for a site.

        Args:
            site_id: Site ID.
            start_date: Optional start date filter.
            end_date: Optional end date filter.
            time_unit: Time unit (DAY, MONTH, YEAR).

        Returns:
            List of energy readings.
        """
        stmt = select(EnergyReading).where(
            EnergyReading.site_id == site_id,
            EnergyReading.time_unit == time_unit,
        )

        if start_date:
            stmt = stmt.where(EnergyReading.reading_date >= start_date)
        if end_date:
            stmt = stmt.where(EnergyReading.reading_date <= end_date)

        stmt = stmt.order_by(EnergyReading.reading_date)
        return list(self.session.scalars(stmt).all())

    def get_latest(self, site_id: int, time_unit: str = "DAY") -> EnergyReading | None:
        """Get the latest energy reading for a site.

        Args:
            site_id: Site ID.
            time_unit: Time unit (DAY, MONTH, YEAR).

        Returns:
            Latest energy reading or None.
        """
        stmt = (
            select(EnergyReading)
            .where(
                EnergyReading.site_id == site_id,
                EnergyReading.time_unit == time_unit,
            )
            .order_by(EnergyReading.reading_date.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def upsert_batch(self, readings: list[dict]) -> int:
        """Insert or update multiple energy readings.

        Args:
            readings: List of dictionaries with energy reading attributes.

        Returns:
            Number of records affected.
        """
        if not readings:
            return 0

        dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"

        for reading in readings:
            if dialect == "postgresql":
                stmt = pg_insert(EnergyReading).values(**reading)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_energy_reading",
                    set_={"energy_wh": reading.get("energy_wh")},
                )
            else:
                stmt = sqlite_insert(EnergyReading).values(**reading)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["site_id", "reading_date", "time_unit"],
                    set_={"energy_wh": reading.get("energy_wh")},
                )
            self.session.execute(stmt)

        self.session.flush()
        return len(readings)
