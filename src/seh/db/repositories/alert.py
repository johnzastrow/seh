"""Alert repository."""

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from seh.db.models.alert import Alert
from seh.db.repositories.base import BaseRepository


class AlertRepository(BaseRepository[Alert]):
    """Repository for Alert operations."""

    model = Alert

    def get_by_site_id(self, site_id: int) -> list[Alert]:
        """Get all alerts for a site.

        Args:
            site_id: Site ID.

        Returns:
            List of alerts.
        """
        stmt = select(Alert).where(Alert.site_id == site_id).order_by(Alert.alert_timestamp.desc())
        return list(self.session.scalars(stmt).all())

    def get_by_alert_id(self, site_id: int, alert_id: int) -> Alert | None:
        """Get alert by site and alert ID.

        Args:
            site_id: Site ID.
            alert_id: Alert ID from SolarEdge.

        Returns:
            Alert or None.
        """
        stmt = select(Alert).where(
            Alert.site_id == site_id,
            Alert.alert_id == alert_id,
        )
        return self.session.scalar(stmt)

    def upsert(self, data: dict) -> Alert:
        """Insert or update an alert.

        Args:
            data: Dictionary of alert attributes.

        Returns:
            The upserted alert.
        """
        dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"

        update_set = {k: v for k, v in data.items() if k not in ("site_id", "alert_id")}

        if dialect == "postgresql":
            stmt = pg_insert(Alert).values(**data)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_alert",
                set_=update_set,
            )
        elif dialect in ("mysql", "mariadb"):
            stmt = mysql_insert(Alert).values(**data)
            stmt = stmt.on_duplicate_key_update(**update_set)
        else:
            stmt = sqlite_insert(Alert).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["site_id", "alert_id"],
                set_=update_set,
            )

        self.session.execute(stmt)
        self.session.flush()

        return self.get_by_alert_id(data["site_id"], data["alert_id"])  # type: ignore
