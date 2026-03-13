"""Power reading and power flow ORM models."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from seh.db.base import Base, TimestampMixin


class PowerReading(Base, TimestampMixin):
    """Power reading at a point in time (typically 15-minute intervals)."""

    __tablename__ = "seh_power_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seh_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    power_watts: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationship
    site: Mapped["Site"] = relationship("Site", back_populates="power_readings")  # type: ignore[name-defined] # noqa: F821

    __table_args__ = (
        UniqueConstraint("site_id", "timestamp", name="uq_power_reading"),
    )

    def __repr__(self) -> str:
        return f"<PowerReading(site={self.site_id}, ts={self.timestamp}, w={self.power_watts})>"


class PowerFlow(Base, TimestampMixin):
    """Power flow snapshot showing PV, grid, load, and storage power."""

    __tablename__ = "seh_power_flows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seh_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Grid connection
    grid_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    grid_power: Mapped[float | None] = mapped_column(Float, nullable=True)

    # PV production
    pv_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pv_power: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Load consumption
    load_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    load_power: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Storage
    storage_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    storage_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    storage_charge_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    storage_critical: Mapped[bool | None] = mapped_column(default=False)

    # Relationship
    site: Mapped["Site"] = relationship("Site", back_populates="power_flows")  # type: ignore[name-defined] # noqa: F821

    __table_args__ = (
        UniqueConstraint("site_id", "timestamp", name="uq_power_flow"),
    )

    def __repr__(self) -> str:
        return f"<PowerFlow(site={self.site_id}, ts={self.timestamp})>"


class PowerDetails(Base, TimestampMixin):
    """Detailed power breakdown at 15-minute intervals from the powerDetails API.

    All power values are in Watts (W), as returned by the SolarEdge API.
    Unlike PowerFlow (real-time snapshot), this is a historical time series.
    """

    __tablename__ = "seh_power_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seh_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Direct meter values from SolarEdge powerDetails endpoint (all in Watts)
    production_w: Mapped[float | None] = mapped_column(Float, nullable=True)       # PV output
    consumption_w: Mapped[float | None] = mapped_column(Float, nullable=True)      # Home load
    self_consumption_w: Mapped[float | None] = mapped_column(Float, nullable=True) # Solar used on-site
    feed_in_w: Mapped[float | None] = mapped_column(Float, nullable=True)          # Exported to grid
    purchased_w: Mapped[float | None] = mapped_column(Float, nullable=True)        # Imported from grid

    # Relationship
    site: Mapped["Site"] = relationship("Site", back_populates="power_details")  # type: ignore[name-defined] # noqa: F821

    __table_args__ = (
        UniqueConstraint("site_id", "timestamp", name="uq_power_details"),
    )

    def __repr__(self) -> str:
        return f"<PowerDetails(site={self.site_id}, ts={self.timestamp}, prod={self.production_w}W)>"
