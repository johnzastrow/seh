"""Equipment sync strategy."""

import contextlib
from datetime import datetime

import structlog

from seh.db.repositories.equipment import EquipmentRepository
from seh.sync.strategies.base import BaseSyncStrategy

logger = structlog.get_logger(__name__)


class EquipmentSyncStrategy(BaseSyncStrategy):
    """Sync strategy for equipment data."""

    data_type = "equipment"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync equipment list.

        Args:
            site_id: Site ID.
            full: Ignored for equipment sync (always fetches latest).

        Returns:
            Number of records synced.
        """
        logger.info("Syncing equipment", site_id=site_id)

        try:
            equipment_list = await self.client.get_equipment(site_id)

            if not equipment_list:
                logger.info("No equipment found", site_id=site_id)
                self.update_sync_metadata(site_id, datetime.now(), 0)
                return 0

            repo = EquipmentRepository(self.session)
            count = 0

            for equip in equipment_list:
                serial = equip.get("SN") or equip.get("serialNumber")
                if not serial:
                    logger.warning("Equipment missing serial number", equipment=equip)
                    continue

                db_data = {
                    "site_id": site_id,
                    "serial_number": serial,
                    "name": equip.get("name"),
                    "manufacturer": equip.get("manufacturer"),
                    "model": equip.get("model"),
                    "equipment_type": equip.get("type", "Inverter"),
                    "communication_method": equip.get("communicationMethod"),
                    "cpu_version": equip.get("cpuVersion"),
                    "dsp1_version": equip.get("dsp1Version"),
                    "dsp2_version": equip.get("dsp2Version"),
                    "connected_optimizers": equip.get("connectedOptimizers"),
                }

                # Parse last report date
                if equip.get("lastReportDate"):
                    with contextlib.suppress(ValueError, AttributeError):
                        db_data["last_report_date"] = datetime.fromisoformat(
                            equip["lastReportDate"].replace("Z", "+00:00")
                        )

                repo.upsert(db_data)
                count += 1

            self.update_sync_metadata(site_id, datetime.now(), count)
            logger.info("Equipment sync complete", site_id=site_id, count=count)
            return count

        except Exception as e:
            logger.error("Equipment sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
