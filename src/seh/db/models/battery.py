"""Battery ORM model."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from seh.db.base import Base, TimestampMixin


class Battery(Base, TimestampMixin):
    """Battery/storage unit associated with a site."""

    __tablename__ = "seh_batteries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seh_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    serial_number: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    firmware_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    capacity: Mapped[float | None] = mapped_column(Float, nullable=True)
    nameplate_capacity: Mapped[float | None] = mapped_column(Float, nullable=True)
    connected_inverter_sn: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Telemetry snapshot
    last_state_of_charge: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_telemetry_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Lifetime energy
    lifetime_energy_charged: Mapped[float | None] = mapped_column(Float, nullable=True)
    lifetime_energy_discharged: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationship
    site: Mapped["Site"] = relationship("Site", back_populates="batteries")  # type: ignore[name-defined] # noqa: F821

    def __repr__(self) -> str:
        return f"<Battery(serial={self.serial_number}, model={self.model})>"
