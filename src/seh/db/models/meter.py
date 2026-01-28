"""Meter and meter reading ORM models."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from seh.db.base import Base, TimestampMixin


class Meter(Base, TimestampMixin):
    """Meter device associated with a site."""

    __tablename__ = "meters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meter_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    connection_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    form: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationship
    site: Mapped["Site"] = relationship("Site", back_populates="meters")  # type: ignore[name-defined] # noqa: F821
    readings: Mapped[list["MeterReading"]] = relationship(
        "MeterReading", back_populates="meter", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("site_id", "name", name="uq_meter_site_name"),
    )

    def __repr__(self) -> str:
        return f"<Meter(name={self.name}, type={self.meter_type})>"


class MeterReading(Base, TimestampMixin):
    """Meter reading at a point in time."""

    __tablename__ = "meter_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meter_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Power and energy values
    power: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy_lifetime: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Voltage and current (optional, depending on meter type)
    voltage_l1: Mapped[float | None] = mapped_column(Float, nullable=True)
    voltage_l2: Mapped[float | None] = mapped_column(Float, nullable=True)
    voltage_l3: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_l1: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_l2: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_l3: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Power factor
    power_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_factor_l1: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_factor_l2: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_factor_l3: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationship
    meter: Mapped["Meter"] = relationship("Meter", back_populates="readings")

    __table_args__ = (
        UniqueConstraint("meter_id", "timestamp", name="uq_meter_reading"),
    )

    def __repr__(self) -> str:
        return f"<MeterReading(meter={self.meter_id}, ts={self.timestamp})>"
