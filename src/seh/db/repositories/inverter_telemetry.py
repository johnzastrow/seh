"""Inverter telemetry repository."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from seh.db.models.inverter_telemetry import InverterTelemetry
from seh.db.repositories.base import BaseRepository


class InverterTelemetryRepository(BaseRepository[InverterTelemetry]):
    """Repository for InverterTelemetry operations."""

    model = InverterTelemetry

    def get_by_site_id(
        self, site_id: int, serial_number: str | None = None
    ) -> list[InverterTelemetry]:
        """Get all telemetry records for a site.

        Args:
            site_id: Site ID.
            serial_number: Optional inverter serial number filter.

        Returns:
            List of telemetry records.
        """
        stmt = select(InverterTelemetry).where(InverterTelemetry.site_id == site_id)
        if serial_number:
            stmt = stmt.where(InverterTelemetry.serial_number == serial_number)
        stmt = stmt.order_by(InverterTelemetry.timestamp.desc())
        return list(self.session.scalars(stmt).all())

    def get_latest(self, site_id: int, serial_number: str) -> InverterTelemetry | None:
        """Get latest telemetry for an inverter.

        Args:
            site_id: Site ID.
            serial_number: Inverter serial number.

        Returns:
            Latest telemetry or None.
        """
        stmt = (
            select(InverterTelemetry)
            .where(
                InverterTelemetry.site_id == site_id,
                InverterTelemetry.serial_number == serial_number,
            )
            .order_by(InverterTelemetry.timestamp.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def get_by_key(
        self, site_id: int, serial_number: str, timestamp: datetime
    ) -> InverterTelemetry | None:
        """Get telemetry by unique key.

        Args:
            site_id: Site ID.
            serial_number: Inverter serial number.
            timestamp: Reading timestamp.

        Returns:
            InverterTelemetry or None.
        """
        stmt = select(InverterTelemetry).where(
            InverterTelemetry.site_id == site_id,
            InverterTelemetry.serial_number == serial_number,
            InverterTelemetry.timestamp == timestamp,
        )
        return self.session.scalar(stmt)

    def upsert(self, data: dict) -> InverterTelemetry:
        """Insert or update an inverter telemetry record.

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
            stmt = pg_insert(InverterTelemetry).values(**data)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_inverter_telemetry",
                set_=update_set,
            )
        elif dialect in ("mysql", "mariadb"):
            stmt = mysql_insert(InverterTelemetry).values(**data)
            stmt = stmt.on_duplicate_key_update(**update_set)
        else:
            stmt = sqlite_insert(InverterTelemetry).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["site_id", "serial_number", "timestamp"],
                set_=update_set,
            )

        self.session.execute(stmt)
        self.session.flush()

        return self.get_by_key(
            data["site_id"], data["serial_number"], data["timestamp"]
        )  # type: ignore
