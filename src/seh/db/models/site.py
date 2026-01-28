"""Site ORM model."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from seh.db.base import Base, TimestampMixin


class Site(Base, TimestampMixin):
    """SolarEdge installation site."""

    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    peak_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_update_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    installation_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    site_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Location fields
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Primary module info
    primary_module_manufacturer: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    primary_module_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    primary_module_power: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Public settings
    is_public: Mapped[bool | None] = mapped_column(default=False)
    public_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    equipment: Mapped[list["Equipment"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Equipment", back_populates="site", cascade="all, delete-orphan"
    )
    batteries: Mapped[list["Battery"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Battery", back_populates="site", cascade="all, delete-orphan"
    )
    energy_readings: Mapped[list["EnergyReading"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "EnergyReading", back_populates="site", cascade="all, delete-orphan"
    )
    power_readings: Mapped[list["PowerReading"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "PowerReading", back_populates="site", cascade="all, delete-orphan"
    )
    power_flows: Mapped[list["PowerFlow"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "PowerFlow", back_populates="site", cascade="all, delete-orphan"
    )
    meters: Mapped[list["Meter"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Meter", back_populates="site", cascade="all, delete-orphan"
    )
    sync_metadata: Mapped[list["SyncMetadata"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "SyncMetadata", back_populates="site", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Alert", back_populates="site", cascade="all, delete-orphan"
    )
    environmental_benefits: Mapped[list["EnvironmentalBenefits"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "EnvironmentalBenefits", back_populates="site", cascade="all, delete-orphan"
    )
    inventory: Mapped[list["InventoryItem"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "InventoryItem", back_populates="site", cascade="all, delete-orphan"
    )
    inverter_telemetry: Mapped[list["InverterTelemetry"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "InverterTelemetry", back_populates="site", cascade="all, delete-orphan"
    )
    optimizer_telemetry: Mapped[list["OptimizerTelemetry"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "OptimizerTelemetry", back_populates="site", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Site(id={self.id}, name='{self.name}')>"
