"""Battery repository."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from seh.db.models.battery import Battery
from seh.db.repositories.base import BaseRepository


class BatteryRepository(BaseRepository[Battery]):
    """Repository for Battery operations."""

    model = Battery

    def get_by_site_id(self, site_id: int) -> list[Battery]:
        """Get all batteries for a site.

        Args:
            site_id: Site ID.

        Returns:
            List of batteries.
        """
        stmt = select(Battery).where(Battery.site_id == site_id)
        return list(self.session.scalars(stmt).all())

    def get_by_serial(self, serial_number: str) -> Battery | None:
        """Get battery by serial number.

        Args:
            serial_number: Battery serial number.

        Returns:
            Battery or None.
        """
        stmt = select(Battery).where(Battery.serial_number == serial_number)
        return self.session.scalar(stmt)

    def upsert(self, battery_data: dict) -> Battery:
        """Insert or update a battery.

        Args:
            battery_data: Dictionary of battery attributes.

        Returns:
            The upserted battery.
        """
        dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"

        if dialect == "postgresql":
            stmt = pg_insert(Battery).values(**battery_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["serial_number"],
                set_={k: v for k, v in battery_data.items() if k != "serial_number"},
            )
        else:
            stmt = sqlite_insert(Battery).values(**battery_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["serial_number"],
                set_={k: v for k, v in battery_data.items() if k != "serial_number"},
            )

        self.session.execute(stmt)
        self.session.flush()

        return self.get_by_serial(battery_data["serial_number"])  # type: ignore
