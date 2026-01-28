"""Power reading and power flow repositories."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from seh.db.models.power import PowerFlow, PowerReading
from seh.db.repositories.base import BaseRepository


class PowerRepository(BaseRepository[PowerReading]):
    """Repository for PowerReading operations."""

    model = PowerReading

    def get_by_site_id(
        self,
        site_id: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[PowerReading]:
        """Get power readings for a site.

        Args:
            site_id: Site ID.
            start_time: Optional start time filter.
            end_time: Optional end time filter.

        Returns:
            List of power readings.
        """
        stmt = select(PowerReading).where(PowerReading.site_id == site_id)

        if start_time:
            stmt = stmt.where(PowerReading.timestamp >= start_time)
        if end_time:
            stmt = stmt.where(PowerReading.timestamp <= end_time)

        stmt = stmt.order_by(PowerReading.timestamp)
        return list(self.session.scalars(stmt).all())

    def get_latest(self, site_id: int) -> PowerReading | None:
        """Get the latest power reading for a site.

        Args:
            site_id: Site ID.

        Returns:
            Latest power reading or None.
        """
        stmt = (
            select(PowerReading)
            .where(PowerReading.site_id == site_id)
            .order_by(PowerReading.timestamp.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def upsert_batch(self, readings: list[dict]) -> int:
        """Insert or update multiple power readings.

        Args:
            readings: List of dictionaries with power reading attributes.

        Returns:
            Number of records affected.
        """
        if not readings:
            return 0

        dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"

        for reading in readings:
            if dialect == "postgresql":
                stmt = pg_insert(PowerReading).values(**reading)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_power_reading",
                    set_={"power_watts": reading.get("power_watts")},
                )
            else:
                stmt = sqlite_insert(PowerReading).values(**reading)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["site_id", "timestamp"],
                    set_={"power_watts": reading.get("power_watts")},
                )
            self.session.execute(stmt)

        self.session.flush()
        return len(readings)


class PowerFlowRepository(BaseRepository[PowerFlow]):
    """Repository for PowerFlow operations."""

    model = PowerFlow

    def get_by_site_id(
        self,
        site_id: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[PowerFlow]:
        """Get power flows for a site.

        Args:
            site_id: Site ID.
            start_time: Optional start time filter.
            end_time: Optional end time filter.

        Returns:
            List of power flows.
        """
        stmt = select(PowerFlow).where(PowerFlow.site_id == site_id)

        if start_time:
            stmt = stmt.where(PowerFlow.timestamp >= start_time)
        if end_time:
            stmt = stmt.where(PowerFlow.timestamp <= end_time)

        stmt = stmt.order_by(PowerFlow.timestamp)
        return list(self.session.scalars(stmt).all())

    def get_latest(self, site_id: int) -> PowerFlow | None:
        """Get the latest power flow for a site.

        Args:
            site_id: Site ID.

        Returns:
            Latest power flow or None.
        """
        stmt = (
            select(PowerFlow)
            .where(PowerFlow.site_id == site_id)
            .order_by(PowerFlow.timestamp.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def upsert(self, flow_data: dict) -> PowerFlow:
        """Insert or update a power flow.

        Args:
            flow_data: Dictionary of power flow attributes.

        Returns:
            The upserted power flow.
        """
        dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"

        update_set = {k: v for k, v in flow_data.items() if k not in ("site_id", "timestamp")}

        if dialect == "postgresql":
            stmt = pg_insert(PowerFlow).values(**flow_data)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_power_flow",
                set_=update_set,
            )
        else:
            stmt = sqlite_insert(PowerFlow).values(**flow_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["site_id", "timestamp"],
                set_=update_set,
            )

        self.session.execute(stmt)
        self.session.flush()

        # Return the latest for this site/timestamp
        result_stmt = (
            select(PowerFlow)
            .where(
                PowerFlow.site_id == flow_data["site_id"],
                PowerFlow.timestamp == flow_data["timestamp"],
            )
        )
        return self.session.scalar(result_stmt)  # type: ignore
