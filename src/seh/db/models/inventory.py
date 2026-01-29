"""Inventory ORM model."""

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from seh.db.base import Base, TimestampMixin


class InventoryItem(Base, TimestampMixin):
    """Inventory item for a site."""

    __tablename__ = "seh_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seh_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Item identification
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Item details
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)  # inverters, optimizers, gateways, etc.
    firmware_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cpu_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    connected_optimizers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    connected_to: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # For modules/panels
    max_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Additional info
    short_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationship
    site: Mapped["Site"] = relationship("Site", back_populates="inventory")  # type: ignore[name-defined] # noqa: F821

    __table_args__ = (
        UniqueConstraint("site_id", "name", "serial_number", name="uq_inventory_item"),
    )

    def __repr__(self) -> str:
        return f"<InventoryItem(site={self.site_id}, name={self.name}, category={self.category})>"
