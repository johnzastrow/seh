"""Optimizer telemetry sync strategy."""

import contextlib
from datetime import datetime, timedelta

import structlog

from seh.db.repositories.equipment import EquipmentRepository
from seh.db.repositories.optimizer_telemetry import OptimizerTelemetryRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.utils.exceptions import APIError

logger = structlog.get_logger(__name__)


class OptimizerTelemetrySyncStrategy(BaseSyncStrategy):
    """Sync strategy for optimizer telemetry data."""

    data_type = "optimizer_telemetry"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync optimizer telemetry for a site.

        Args:
            site_id: Site ID.
            full: If True, sync more historical data.

        Returns:
            Number of records synced.
        """
        logger.info("Syncing optimizer telemetry", site_id=site_id, full=full)

        try:
            # Get optimizers for this site from equipment
            equipment_repo = EquipmentRepository(self.session)
            equipment = equipment_repo.get_by_site_id(site_id)
            optimizers = [e for e in equipment if e.equipment_type == "Optimizer"]

            if not optimizers:
                logger.info("No optimizers found for site", site_id=site_id)
                self.update_sync_metadata(site_id, datetime.now(), 0)
                return 0

            # Determine time range
            if full:
                start_time = datetime.now() - timedelta(days=self.settings.power_lookback_days)
            else:
                start_time = self.get_start_time(site_id, lookback_days=1)

            end_time = datetime.now()

            repo = OptimizerTelemetryRepository(self.session)
            total_synced = 0
            latest_timestamp = None

            for optimizer in optimizers:
                serial_number = optimizer.serial_number
                if not serial_number:
                    continue

                try:
                    telemetry = await self.client.get_optimizer_data(
                        site_id, serial_number, start_time, end_time
                    )

                    for reading in telemetry:
                        # Parse timestamp
                        timestamp = None
                        if reading.get("date"):
                            with contextlib.suppress(ValueError, AttributeError):
                                timestamp = datetime.strptime(
                                    reading["date"], "%Y-%m-%d %H:%M:%S"
                                )

                        if not timestamp:
                            continue

                        db_data = {
                            "site_id": site_id,
                            "serial_number": serial_number,
                            "inverter_serial": optimizer.inverter_serial,
                            "timestamp": timestamp,
                            "panel_id": reading.get("panelId"),
                            "dc_voltage": reading.get("dcVoltage"),
                            "dc_current": reading.get("dcCurrent"),
                            "dc_power": reading.get("dcPower"),
                            "output_voltage": reading.get("outputVoltage"),
                            "output_current": reading.get("outputCurrent"),
                            "output_power": reading.get("outputPower"),
                            "energy": reading.get("energy"),
                            "lifetime_energy": reading.get("lifetimeEnergy"),
                            "temperature": reading.get("temperature"),
                            "optimizer_mode": reading.get("optimizerMode"),
                        }

                        repo.upsert(db_data)
                        total_synced += 1

                        if latest_timestamp is None or timestamp > latest_timestamp:
                            latest_timestamp = timestamp

                    logger.debug(
                        "Synced optimizer telemetry",
                        site_id=site_id,
                        serial_number=serial_number,
                        records=len(telemetry),
                    )

                except APIError as e:
                    if e.status_code in (400, 403):
                        logger.info(
                            "Optimizer telemetry not available",
                            site_id=site_id,
                            serial_number=serial_number,
                        )
                        continue
                    raise

            self.update_sync_metadata(site_id, latest_timestamp or datetime.now(), total_synced)
            logger.info(
                "Optimizer telemetry sync complete",
                site_id=site_id,
                records=total_synced,
            )
            return total_synced

        except Exception as e:
            logger.error("Optimizer telemetry sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
