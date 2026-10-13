"""Inventory sync strategy."""

from datetime import datetime
from typing import Any

import structlog

from seh.db.repositories.inventory import InventoryRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.sync.v2_fields import INVENTORY_CATEGORIES, model_name

logger = structlog.get_logger(__name__)


class InventorySyncStrategy(BaseSyncStrategy):
    """Sync strategy for the device inventory (GET /sites/{id}/devices, all types)."""

    data_type = "inventory"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync all devices (inverters, meters, batteries, optimizers) into seh_inventory.

        Rows are keyed by (site, name, serial) as in V1, so existing inverter and meter
        rows are updated in place; optimizers are new in V2 and use category "optimizers".

        Args:
            site_id: Site ID.
            full: Ignored for inventory sync (always fetches all).

        Returns:
            Number of records synced.
        """
        logger.info("Syncing inventory", site_id=site_id)

        try:
            devices = await self.client.get_devices(site_id)

            repo = InventoryRepository(self.session)
            synced = 0
            for device in devices:
                device_type = str(device.get("type") or "").upper()
                name = device.get("name") or model_name(device)
                if not name:
                    continue

                db_data: dict[str, Any] = {
                    "site_id": site_id,
                    "name": name,
                    "manufacturer": device.get("manufacturer"),
                    "model": model_name(device),
                    # V1 stored "" for devices without a serial; keep the unique key stable.
                    "serial_number": device.get("serialNumber") or "",
                    "category": INVENTORY_CATEGORIES.get(device_type, f"{device_type.lower()}s"),
                    "connected_to": device.get("connectedTo"),
                    "max_power": device.get("nameplate"),
                    "connected_optimizers": device.get("connectedOptimizers"),
                }
                # V1 reported an inverter's firmware as cpu_version, other devices' as
                # firmware_version; keep that split so values stay comparable.
                firmware_column = "cpu_version" if device_type == "INVERTER" else "firmware_version"
                db_data[firmware_column] = device.get("firmwareVersion")

                repo.upsert(db_data)
                synced += 1

            self.update_sync_metadata(site_id, datetime.now(), synced)
            logger.info("Inventory sync complete", site_id=site_id, items_synced=synced)
            return synced

        except Exception as e:
            if self.skip_if_unavailable(site_id, e):
                return 0
            logger.error("Inventory sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
