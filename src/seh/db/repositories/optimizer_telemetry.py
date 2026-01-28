"""Optimizer telemetry repository."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from seh.db.models.optimizer_telemetry import OptimizerTelemetry
from seh.db.repositories.base import BaseRepository


class OptimizerTelemetryRepository(BaseRepository[OptimizerTelemetry]):
    """Repository for OptimizerTelemetry operations."""

    model = OptimizerTelemetry

    def get_by_site_id(
        self, site_id: int, serial_number: str | None = None
    ) -> list[OptimizerTelemetry]:
        """Get all telemetry records for a site.

        Args:
            site_id: Site ID.
            serial_number: Optional optimizer serial number filter.

        Returns:
            List of telemetry records.
        """
        stmt = select(OptimizerTelemetry).where(OptimizerTelemetry.site_id == site_id)
        if serial_number:
            stmt = stmt.where(OptimizerTelemetry.serial_number == serial_number)
        stmt = stmt.order_by(OptimizerTelemetry.timestamp.desc())
        return list(self.session.scalars(stmt).all())

    def get_latest(self, site_id: int, serial_number: str) -> OptimizerTelemetry | None:
        """Get latest telemetry for an optimizer.

        Args:
            site_id: Site ID.
            serial_number: Optimizer serial number.

        Returns:
            Latest telemetry or None.
        """
        stmt = (
            select(OptimizerTelemetry)
            .where(
                OptimizerTelemetry.site_id == site_id,
                OptimizerTelemetry.serial_number == serial_number,
            )
            .order_by(OptimizerTelemetry.timestamp.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def get_by_key(
        self, site_id: int, serial_number: str, timestamp: datetime
    ) -> OptimizerTelemetry | None:
        """Get telemetry by unique key.

        Args:
            site_id: Site ID.
            serial_number: Optimizer serial number.
            timestamp: Reading timestamp.

        Returns:
            OptimizerTelemetry or None.
        """
        stmt = select(OptimizerTelemetry).where(
            OptimizerTelemetry.site_id == site_id,
            OptimizerTelemetry.serial_number == serial_number,
            OptimizerTelemetry.timestamp == timestamp,
        )
        return self.session.scalar(stmt)

    def upsert(self, data: dict) -> OptimizerTelemetry:
        """Insert or update an optimizer telemetry record.

        Args:
            data: Dictionary of telemetry attributes.

        Returns:
            The upserted record.
        """
        dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"

        update_set = {
            k: v for k, v in data.items() if k not in ("site_id", "serial_number", "timestamp")
        }

        if dialect == "postgresql":
            stmt = pg_insert(OptimizerTelemetry).values(**data)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_optimizer_telemetry",
                set_=update_set,
            )
        elif dialect in ("mysql", "mariadb"):
            stmt = mysql_insert(OptimizerTelemetry).values(**data)
            stmt = stmt.on_duplicate_key_update(**update_set)
        else:
            stmt = sqlite_insert(OptimizerTelemetry).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["site_id", "serial_number", "timestamp"],
                set_=update_set,
            )

        self.session.execute(stmt)
        self.session.flush()

        return self.get_by_key(
            data["site_id"], data["serial_number"], data["timestamp"]
        )  # type: ignore
