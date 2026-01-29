"""Sync metadata ORM model for tracking synchronization state."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from seh.db.base import Base, TimestampMixin


class SyncMetadata(Base, TimestampMixin):
    """Tracks the last successful sync for each site and data type."""

    __tablename__ = "seh_sync_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seh_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    data_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # site, equipment, energy, power, storage, meter
    last_sync_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_data_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    records_synced: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # success, partial, error
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Relationship
    site: Mapped["Site"] = relationship("Site", back_populates="sync_metadata")  # type: ignore[name-defined] # noqa: F821

    __table_args__ = (
        UniqueConstraint("site_id", "data_type", name="uq_sync_metadata"),
    )

    def __repr__(self) -> str:
        return f"<SyncMetadata(site={self.site_id}, type={self.data_type}, last={self.last_sync_time})>"
