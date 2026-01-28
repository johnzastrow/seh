"""Meter and meter reading repositories."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from seh.db.models.meter import Meter, MeterReading
from seh.db.repositories.base import BaseRepository


class MeterRepository(BaseRepository[Meter]):
    """Repository for Meter operations."""

    model = Meter

    def get_by_site_id(self, site_id: int) -> list[Meter]:
        """Get all meters for a site.

        Args:
            site_id: Site ID.

        Returns:
            List of meters.
        """
        stmt = select(Meter).where(Meter.site_id == site_id)
        return list(self.session.scalars(stmt).all())

    def get_by_name(self, site_id: int, name: str) -> Meter | None:
        """Get meter by site and name.

        Args:
            site_id: Site ID.
            name: Meter name.

        Returns:
            Meter or None.
        """
        stmt = select(Meter).where(Meter.site_id == site_id, Meter.name == name)
        return self.session.scalar(stmt)

    def upsert(self, meter_data: dict) -> Meter:
        """Insert or update a meter.

        Args:
            meter_data: Dictionary of meter attributes.

        Returns:
            The upserted meter.
        """
        dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"

        update_set = {k: v for k, v in meter_data.items() if k not in ("site_id", "name")}

        if dialect == "postgresql":
            stmt = pg_insert(Meter).values(**meter_data)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_meter_site_name",
                set_=update_set,
            )
        else:
            stmt = sqlite_insert(Meter).values(**meter_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["site_id", "name"],
                set_=update_set,
            )

        self.session.execute(stmt)
        self.session.flush()

        return self.get_by_name(meter_data["site_id"], meter_data["name"])  # type: ignore


class MeterReadingRepository(BaseRepository[MeterReading]):
    """Repository for MeterReading operations."""

    model = MeterReading

    def get_by_meter_id(
        self,
        meter_id: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[MeterReading]:
        """Get readings for a meter.

        Args:
            meter_id: Meter ID.
            start_time: Optional start time filter.
            end_time: Optional end time filter.

        Returns:
            List of meter readings.
        """
        stmt = select(MeterReading).where(MeterReading.meter_id == meter_id)

        if start_time:
            stmt = stmt.where(MeterReading.timestamp >= start_time)
        if end_time:
            stmt = stmt.where(MeterReading.timestamp <= end_time)

        stmt = stmt.order_by(MeterReading.timestamp)
        return list(self.session.scalars(stmt).all())

    def get_latest(self, meter_id: int) -> MeterReading | None:
        """Get the latest reading for a meter.

        Args:
            meter_id: Meter ID.

        Returns:
            Latest meter reading or None.
        """
        stmt = (
            select(MeterReading)
            .where(MeterReading.meter_id == meter_id)
            .order_by(MeterReading.timestamp.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def upsert_batch(self, readings: list[dict]) -> int:
        """Insert or update multiple meter readings.

        Args:
            readings: List of dictionaries with meter reading attributes.

        Returns:
            Number of records affected.
        """
        if not readings:
            return 0

        dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"

        for reading in readings:
            update_set = {k: v for k, v in reading.items() if k not in ("meter_id", "timestamp")}

            if dialect == "postgresql":
                stmt = pg_insert(MeterReading).values(**reading)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_meter_reading",
                    set_=update_set,
                )
            else:
                stmt = sqlite_insert(MeterReading).values(**reading)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["meter_id", "timestamp"],
                    set_=update_set,
                )
            self.session.execute(stmt)

        self.session.flush()
        return len(readings)
