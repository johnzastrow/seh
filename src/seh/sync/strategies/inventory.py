"""Inventory sync strategy."""

from datetime import datetime

import structlog

from seh.db.repositories.inventory import InventoryRepository
from seh.sync.strategies.base import BaseSyncStrategy
from seh.utils.exceptions import APIError

logger = structlog.get_logger(__name__)


class InventorySyncStrategy(BaseSyncStrategy):
    """Sync strategy for inventory data."""

    data_type = "inventory"

    async def sync(self, site_id: int, full: bool = False) -> int:
        """Sync inventory for a site.

        Args:
            site_id: Site ID.
            full: Ignored for inventory sync (always fetches all).

        Returns:
            Number of records synced.
        """
        logger.info("Syncing inventory", site_id=site_id)

        try:
            inventory = await self.client.get_inventory(site_id)

            if not inventory:
                logger.info("No inventory for site", site_id=site_id)
                self.update_sync_metadata(site_id, datetime.now(), 0)
                return 0

            repo = InventoryRepository(self.session)
            synced = 0

            # Process each category of inventory items
            for category, items in inventory.items():
                if not isinstance(items, list):
                    continue

                for item in items:
                    name = item.get("name") or item.get("model")
                    if not name:
                        continue

                    db_data = {
                        "site_id": site_id,
                        "name": name,
                        "manufacturer": item.get("manufacturer"),
                        "model": item.get("model"),
                        "serial_number": item.get("SN") or item.get("serialNumber") or "",
                        "category": category,
                        "firmware_version": item.get("firmwareVersion"),
                        "connected_optimizers": item.get("connectedOptimizers"),
                        "cpu_version": item.get("cpuVersion"),
                    }

                    repo.upsert(db_data)
                    synced += 1

            self.update_sync_metadata(site_id, datetime.now(), synced)
            logger.info("Inventory sync complete", site_id=site_id, items_synced=synced)
            return synced

        except APIError as e:
            if e.status_code == 400:
                logger.info("Inventory not available for site", site_id=site_id)
                self.update_sync_metadata(site_id, datetime.now(), 0)
                return 0
            raise
        except Exception as e:
            logger.error("Inventory sync failed", site_id=site_id, error=str(e))
            self.update_sync_metadata(site_id, None, 0, "error", str(e)[:500])
            raise
