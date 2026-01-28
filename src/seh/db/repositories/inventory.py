"""Inventory repository."""

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from seh.db.models.inventory import InventoryItem
from seh.db.repositories.base import BaseRepository


class InventoryRepository(BaseRepository[InventoryItem]):
    """Repository for InventoryItem operations."""

    model = InventoryItem

    def get_by_site_id(self, site_id: int) -> list[InventoryItem]:
        """Get all inventory items for a site.

        Args:
            site_id: Site ID.

        Returns:
            List of inventory items.
        """
        stmt = select(InventoryItem).where(InventoryItem.site_id == site_id)
        return list(self.session.scalars(stmt).all())

    def get_by_name_serial(
        self, site_id: int, name: str, serial_number: str | None
    ) -> InventoryItem | None:
        """Get inventory item by site, name, and serial number.

        Args:
            site_id: Site ID.
            name: Item name.
            serial_number: Item serial number.

        Returns:
            InventoryItem or None.
        """
        stmt = select(InventoryItem).where(
            InventoryItem.site_id == site_id,
            InventoryItem.name == name,
            InventoryItem.serial_number == serial_number,
        )
        return self.session.scalar(stmt)

    def upsert(self, data: dict) -> InventoryItem:
        """Insert or update an inventory item.

        Args:
            data: Dictionary of inventory item attributes.

        Returns:
            The upserted inventory item.
        """
        dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"

        update_set = {
            k: v for k, v in data.items() if k not in ("site_id", "name", "serial_number")
        }

        if dialect == "postgresql":
            stmt = pg_insert(InventoryItem).values(**data)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_inventory_item",
                set_=update_set,
            )
        elif dialect in ("mysql", "mariadb"):
            stmt = mysql_insert(InventoryItem).values(**data)
            stmt = stmt.on_duplicate_key_update(**update_set)
        else:
            stmt = sqlite_insert(InventoryItem).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["site_id", "name", "serial_number"],
                set_=update_set,
            )

        self.session.execute(stmt)
        self.session.flush()

        return self.get_by_name_serial(
            data["site_id"], data["name"], data.get("serial_number")
        )  # type: ignore
