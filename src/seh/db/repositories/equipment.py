"""Equipment repository."""

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from seh.db.models.equipment import Equipment
from seh.db.repositories.base import BaseRepository


class EquipmentRepository(BaseRepository[Equipment]):
    """Repository for Equipment operations."""

    model = Equipment

    def get_by_site_id(self, site_id: int) -> list[Equipment]:
        """Get all equipment for a site.

        Args:
            site_id: Site ID.

        Returns:
            List of equipment.
        """
        stmt = select(Equipment).where(Equipment.site_id == site_id)
        return list(self.session.scalars(stmt).all())

    def get_by_serial(self, serial_number: str) -> Equipment | None:
        """Get equipment by serial number.

        Args:
            serial_number: Equipment serial number.

        Returns:
            Equipment or None.
        """
        stmt = select(Equipment).where(Equipment.serial_number == serial_number)
        return self.session.scalar(stmt)

    def upsert(self, equipment_data: dict) -> Equipment:
        """Insert or update equipment.

        Args:
            equipment_data: Dictionary of equipment attributes.

        Returns:
            The upserted equipment.
        """
        dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"
        update_set = {k: v for k, v in equipment_data.items() if k != "serial_number"}

        if dialect == "postgresql":
            stmt = pg_insert(Equipment).values(**equipment_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["serial_number"],
                set_=update_set,
            )
        elif dialect in ("mysql", "mariadb"):
            stmt = mysql_insert(Equipment).values(**equipment_data)
            stmt = stmt.on_duplicate_key_update(**update_set)
        else:
            stmt = sqlite_insert(Equipment).values(**equipment_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["serial_number"],
                set_=update_set,
            )

        self.session.execute(stmt)
        self.session.flush()

        return self.get_by_serial(equipment_data["serial_number"])  # type: ignore
