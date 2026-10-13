"""Inverter telemetry sync strategy."""

from datetime import datetime, timedelta
from typing import Any

import structlog

from seh.db.repositories.inverter_telemetry import InverterTelemetryRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.sync.v2_fields import site_local

logger = structlog.get_logger(__name__)

# V2 metric -> seh_inverter_telemetry column(s). V2 power is the total AC output, which V1
# stored both as total_active_power and (for single-phase inverters) L1 active_power.
METRIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "power": ("total_active_power", "active_power"),
    "voltage": ("ac_voltage",),
    "current": ("ac_current",),
    "frequency": ("ac_frequency",),
}


class InverterTelemetrySyncStrategy(BaseSyncStrategy):
    """Sync strategy for inverter telemetry (GET /sites/{id}/inverters/telemetry)."""

    data_type = "inverter_telemetry"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync 15-minute inverter telemetry for all of the site's inverters.

        V2 provides 15-minute averages (V1 had ~5-minute samples) and no temperature,
        inverter/operation mode, DC voltage, power limit, or reactive power; those
        columns are NULL in V2 rows. V2's per-interval energy is not stored because
        total_energy held V1's lifetime counter.

        Args:
            site_id: Site ID.
            full: If True, sync from lookback date regardless of last sync.

        Returns:
            Number of records synced.
        """
        logger.info("Syncing inverter telemetry", site_id=site_id, full=full)

        try:
            end_time = datetime.now()
            if full:
                start_time = end_time - timedelta(days=self.settings.power_lookback_days)
            else:
                start_time = self.get_start_time(site_id, lookback_days=1)

            inverters = await self.client.get_inverters_telemetry(
                site_id, start_time, end_time, resolution="QUARTER_HOUR"
            )

            repo = InverterTelemetryRepository(self.session)
            count = 0
            latest: datetime | None = None
            for serial, metrics in inverters.items():
                rows: dict[datetime, dict[str, Any]] = {}
                for metric, columns in METRIC_COLUMNS.items():
                    series: dict[str, Any] = metrics.get(metric) or {}
                    for point in series.get("values") or []:
                        timestamp = site_local(point.get("timestamp"))
                        value = point.get("value")
                        if timestamp is None or value is None:
                            continue
                        row = rows.setdefault(timestamp, {})
                        for column in columns:
                            row[column] = value

                for timestamp, values in sorted(rows.items()):
                    repo.upsert(
                        {
                            "site_id": site_id,
                            "serial_number": serial,
                            "timestamp": timestamp,
                            **values,
                        }
                    )
                    count += 1
                    latest = timestamp if latest is None or timestamp > latest else latest

            self.update_sync_metadata(site_id, latest, count)
            logger.info("Inverter telemetry sync complete", site_id=site_id, count=count)
            return count

        except Exception as e:
            if self.skip_if_unavailable(site_id, e):
                return 0
            logger.error("Inverter telemetry sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
