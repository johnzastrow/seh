"""Equipment ORM model."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from seh.db.base import Base, TimestampMixin


class Equipment(Base, TimestampMixin):
    """Equipment associated with a site (inverters, optimizers, gateways, etc.)."""

    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    serial_number: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    equipment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    communication_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cpu_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    connected_optimizers: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # For inverters
    dsp1_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    dsp2_version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Optimizer-specific fields
    inverter_serial: Mapped[str | None] = mapped_column(String(100), nullable=True)
    panel_manufacturer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    panel_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    last_report_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationship
    site: Mapped["Site"] = relationship("Site", back_populates="equipment")  # type: ignore[name-defined] # noqa: F821

    def __repr__(self) -> str:
        return f"<Equipment(serial={self.serial_number}, type={self.equipment_type})>"
