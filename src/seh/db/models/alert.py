"""Alert ORM model."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from seh.db.base import Base, TimestampMixin


class Alert(Base, TimestampMixin):
    """System alert for a site."""

    __tablename__ = "seh_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seh_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Alert identification
    alert_id: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)  # HIGH, MEDIUM, LOW
    alert_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    alert_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Alert details
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Affected component
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Timestamps
    alert_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationship
    site: Mapped["Site"] = relationship("Site", back_populates="alerts")  # type: ignore[name-defined] # noqa: F821

    __table_args__ = (
        UniqueConstraint("site_id", "alert_id", name="uq_alert"),
    )

    def __repr__(self) -> str:
        return f"<Alert(site={self.site_id}, id={self.alert_id}, severity={self.severity})>"
