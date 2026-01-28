"""Inverter telemetry sync strategy."""

import contextlib
from datetime import datetime, timedelta

import structlog

from seh.db.repositories.equipment import EquipmentRepository
from seh.db.repositories.inverter_telemetry import InverterTelemetryRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.utils.exceptions import APIError

logger = structlog.get_logger(__name__)


class InverterTelemetrySyncStrategy(BaseSyncStrategy):
    """Sync strategy for inverter telemetry data."""

    data_type = "inverter_telemetry"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync inverter telemetry for a site.

        Args:
            site_id: Site ID.
            full: If True, sync more historical data.

        Returns:
            Number of records synced.
        """
        logger.info("Syncing inverter telemetry", site_id=site_id, full=full)

        try:
            # Get inverters for this site
            equipment_repo = EquipmentRepository(self.session)
            equipment = equipment_repo.get_by_site_id(site_id)
            inverters = [e for e in equipment if e.equipment_type == "Inverter"]

            if not inverters:
                logger.info("No inverters found for site", site_id=site_id)
                self.update_sync_metadata(site_id, datetime.now(), 0)
                return 0

            # Determine time range
            if full:
                start_time = datetime.now() - timedelta(days=self.settings.power_lookback_days)
            else:
                start_time = self.get_start_time(site_id, lookback_days=1)

            end_time = datetime.now()

            repo = InverterTelemetryRepository(self.session)
            total_synced = 0
            latest_timestamp = None

            for inverter in inverters:
                serial_number = inverter.serial_number
                if not serial_number:
                    continue

                try:
                    telemetry = await self.client.get_inverter_data(
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

                        # Extract L1 phase data
                        l1_data = reading.get("L1Data", {})

                        db_data = {
                            "site_id": site_id,
                            "serial_number": serial_number,
                            "timestamp": timestamp,
                            "total_active_power": reading.get("totalActivePower"),
                            "total_energy": reading.get("totalEnergy"),
                            "power_limit": reading.get("powerLimit"),
                            "temperature": reading.get("temperature"),
                            "inverter_mode": reading.get("inverterMode"),
                            "operation_mode": reading.get("operationMode"),
                            "ac_current": l1_data.get("acCurrent"),
                            "ac_voltage": l1_data.get("acVoltage"),
                            "ac_frequency": l1_data.get("acFrequency"),
                            "apparent_power": l1_data.get("apparentPower"),
                            "active_power": l1_data.get("activePower"),
                            "reactive_power": l1_data.get("reactivePower"),
                            "cos_phi": l1_data.get("cosPhi"),
                            "dc_voltage": reading.get("dcVoltage"),
                        }

                        repo.upsert(db_data)
                        total_synced += 1

                        if latest_timestamp is None or timestamp > latest_timestamp:
                            latest_timestamp = timestamp

                    logger.debug(
                        "Synced inverter telemetry",
                        site_id=site_id,
                        serial_number=serial_number,
                        records=len(telemetry),
                    )

                except APIError as e:
                    if e.status_code in (400, 403):
                        logger.info(
                            "Inverter telemetry not available",
                            site_id=site_id,
                            serial_number=serial_number,
                        )
                        continue
                    raise

            self.update_sync_metadata(site_id, latest_timestamp or datetime.now(), total_synced)
            logger.info(
                "Inverter telemetry sync complete",
                site_id=site_id,
                records=total_synced,
            )
            return total_synced

        except Exception as e:
            logger.error("Inverter telemetry sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
