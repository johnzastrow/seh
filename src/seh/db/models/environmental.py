"""Environmental benefits ORM model."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from seh.db.base import Base, TimestampMixin


class EnvironmentalBenefits(Base, TimestampMixin):
    """Environmental benefits data for a site."""

    __tablename__ = "environmental_benefits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Gas emission savings
    co2_saved: Mapped[float | None] = mapped_column(Float, nullable=True)
    so2_saved: Mapped[float | None] = mapped_column(Float, nullable=True)
    nox_saved: Mapped[float | None] = mapped_column(Float, nullable=True)
    co2_units: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Trees planted equivalent
    trees_planted: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Light bulbs equivalent
    light_bulbs: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Timestamp of when benefits were calculated
    benefits_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationship
    site: Mapped["Site"] = relationship("Site", back_populates="environmental_benefits")  # type: ignore[name-defined] # noqa: F821

    __table_args__ = (
        UniqueConstraint("site_id", name="uq_environmental_benefits_site"),
    )

    def __repr__(self) -> str:
        return f"<EnvironmentalBenefits(site={self.site_id}, co2={self.co2_saved})>"
