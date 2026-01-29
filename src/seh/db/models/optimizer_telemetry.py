"""Optimizer telemetry ORM model."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from seh.db.base import Base, TimestampMixin


class OptimizerTelemetry(Base, TimestampMixin):
    """Power optimizer telemetry data."""

    __tablename__ = "seh_optimizer_telemetry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seh_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    serial_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    inverter_serial: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Panel position
    panel_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # DC side (from panel)
    dc_voltage: Mapped[float | None] = mapped_column(Float, nullable=True)
    dc_current: Mapped[float | None] = mapped_column(Float, nullable=True)
    dc_power: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Output (to inverter)
    output_voltage: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_current: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_power: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Energy
    energy: Mapped[float | None] = mapped_column(Float, nullable=True)
    lifetime_energy: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Temperature
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Optimizer mode/status
    optimizer_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationship
    site: Mapped["Site"] = relationship("Site", back_populates="optimizer_telemetry")  # type: ignore[name-defined] # noqa: F821

    __table_args__ = (
        UniqueConstraint("site_id", "serial_number", "timestamp", name="uq_optimizer_telemetry"),
    )

    def __repr__(self) -> str:
        return f"<OptimizerTelemetry(site={self.site_id}, sn={self.serial_number}, ts={self.timestamp})>"
