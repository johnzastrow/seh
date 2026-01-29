"""Inverter telemetry ORM model."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from seh.db.base import Base, TimestampMixin


class InverterTelemetry(Base, TimestampMixin):
    """Inverter telemetry data."""

    __tablename__ = "seh_inverter_telemetry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seh_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    serial_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Power and energy
    total_active_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_energy: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_limit: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Inverter status
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    inverter_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    operation_mode: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # AC phase data (L1)
    ac_current: Mapped[float | None] = mapped_column(Float, nullable=True)
    ac_voltage: Mapped[float | None] = mapped_column(Float, nullable=True)
    ac_frequency: Mapped[float | None] = mapped_column(Float, nullable=True)
    apparent_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    reactive_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    cos_phi: Mapped[float | None] = mapped_column(Float, nullable=True)

    # DC side (if available)
    dc_voltage: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationship
    site: Mapped["Site"] = relationship("Site", back_populates="inverter_telemetry")  # type: ignore[name-defined] # noqa: F821

    __table_args__ = (
        UniqueConstraint("site_id", "serial_number", "timestamp", name="uq_inverter_telemetry"),
    )

    def __repr__(self) -> str:
        return f"<InverterTelemetry(site={self.site_id}, sn={self.serial_number}, ts={self.timestamp})>"
