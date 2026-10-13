"""Equipment sync strategy."""

from datetime import datetime
from typing import Any

import structlog

from seh.db.repositories.equipment import EquipmentRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.sync.v2_fields import model_name

logger = structlog.get_logger(__name__)


class EquipmentSyncStrategy(BaseSyncStrategy):
    """Sync strategy for inverters (GET /sites/{id}/devices, type INVERTER)."""

    data_type = "equipment"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync the site's inverters into seh_equipment.

        V2 has no DSP versions or last report date; those columns keep their V1 values.
        The single V2 firmware version is stored as cpu_version, which is where V1 put
        the inverter's main firmware version.

        Args:
            site_id: Site ID.
            full: Ignored for equipment sync (always fetches latest).

        Returns:
            Number of records synced.
        """
        logger.info("Syncing equipment", site_id=site_id)

        try:
            devices = await self.client.get_devices(site_id)
            inverters = [d for d in devices if d.get("type") == "INVERTER"]

            repo = EquipmentRepository(self.session)
            count = 0
            for device in inverters:
                serial = device.get("serialNumber")
                if not serial:
                    logger.warning("Inverter missing serial number", site_id=site_id)
                    continue

                db_data: dict[str, Any] = {
                    "site_id": site_id,
                    "serial_number": serial,
                    "name": device.get("name"),
                    "manufacturer": device.get("manufacturer"),
                    "model": model_name(device),
                    "equipment_type": "Inverter",
                    "communication_method": device.get("communicationType"),
                    "cpu_version": device.get("firmwareVersion"),
                    "connected_optimizers": device.get("connectedOptimizers"),
                }
                repo.upsert(db_data)
                count += 1

            if not inverters:
                logger.info("No equipment found", site_id=site_id)
            self.update_sync_metadata(site_id, datetime.now(), count)
            logger.info("Equipment sync complete", site_id=site_id, count=count)
            return count

        except Exception as e:
            logger.error("Equipment sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
