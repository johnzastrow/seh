"""Energy reading ORM model."""

from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from seh.db.base import Base, TimestampMixin


class EnergyReading(Base, TimestampMixin):
    """Energy production reading (daily or monthly)."""

    __tablename__ = "seh_energy_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seh_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reading_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    time_unit: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DAY"
    )  # DAY, MONTH, YEAR
    energy_wh: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationship
    site: Mapped["Site"] = relationship("Site", back_populates="energy_readings")  # type: ignore[name-defined] # noqa: F821

    __table_args__ = (
        UniqueConstraint("site_id", "reading_date", "time_unit", name="uq_energy_reading"),
    )

    def __repr__(self) -> str:
        return f"<EnergyReading(site={self.site_id}, date={self.reading_date}, wh={self.energy_wh})>"
