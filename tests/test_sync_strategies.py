"""Tests for sync strategies."""

from datetime import datetime, date
from unittest.mock import AsyncMock, MagicMock

import pytest

from seh.db.models import Site, Equipment
from seh.sync.strategies.site import SiteSyncStrategy
from seh.sync.strategies.equipment import EquipmentSyncStrategy
from seh.sync.strategies.energy import EnergySyncStrategy
from seh.sync.strategies.environmental import EnvironmentalSyncStrategy
from seh.sync.strategies.alert import AlertSyncStrategy
from seh.sync.strategies.inventory import InventorySyncStrategy
from seh.utils.exceptions import APIError


class TestSiteSyncStrategy:
    """Test SiteSyncStrategy."""

    @pytest.mark.asyncio
    async def test_sync_site(self, test_session, test_settings, mock_api_client):
        """Test syncing site details."""
        strategy = SiteSyncStrategy(mock_api_client, test_session, test_settings)

        count = await strategy.sync(12345)

        assert count == 1
        mock_api_client.get_site_details.assert_called_once_with(12345)

        # Verify site was created
        site = test_session.get(Site, 12345)
        assert site is not None

    @pytest.mark.asyncio
    async def test_sync_site_no_data(self, test_session, test_settings):
        """Test syncing when API returns no data."""
        client = AsyncMock()
        client.get_site_details.return_value = {}

        strategy = SiteSyncStrategy(client, test_session, test_settings)
        count = await strategy.sync(12345)

        assert count == 0


class TestEquipmentSyncStrategy:
    """Test EquipmentSyncStrategy."""

    @pytest.mark.asyncio
    async def test_sync_equipment(self, test_session, test_settings, mock_api_client):
        """Test syncing equipment."""
        # Create site first
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        strategy = EquipmentSyncStrategy(mock_api_client, test_session, test_settings)

        count = await strategy.sync(12345)

        assert count == 1
        mock_api_client.get_equipment.assert_called_once_with(12345)

        # Verify equipment was created
        equipment = test_session.query(Equipment).filter_by(serial_number="SN123456").first()
        assert equipment is not None
        assert equipment.manufacturer == "SolarEdge"

    @pytest.mark.asyncio
    async def test_sync_equipment_empty(self, test_session, test_settings):
        """Test syncing when no equipment returned."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        client = AsyncMock()
        client.get_equipment.return_value = []

        strategy = EquipmentSyncStrategy(client, test_session, test_settings)
        count = await strategy.sync(12345)

        assert count == 0


class TestEnergySyncStrategy:
    """Test EnergySyncStrategy."""

    @pytest.mark.asyncio
    async def test_sync_energy(self, test_session, test_settings, mock_api_client):
        """Test syncing energy data."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        strategy = EnergySyncStrategy(mock_api_client, test_session, test_settings)

        count = await strategy.sync(12345, full=True)

        assert count == 2
        mock_api_client.get_energy.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_energy_incremental(self, test_session, test_settings, mock_api_client):
        """Test incremental energy sync uses last sync time."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        strategy = EnergySyncStrategy(mock_api_client, test_session, test_settings)

        # First sync
        await strategy.sync(12345, full=True)

        # Incremental sync should still work
        await strategy.sync(12345, full=False)


class TestEnvironmentalSyncStrategy:
    """Test EnvironmentalSyncStrategy."""

    @pytest.mark.asyncio
    async def test_sync_environmental(self, test_session, test_settings, mock_api_client):
        """Test syncing environmental benefits."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        strategy = EnvironmentalSyncStrategy(mock_api_client, test_session, test_settings)

        count = await strategy.sync(12345)

        assert count == 1
        mock_api_client.get_environmental_benefits.assert_called_once_with(12345)

    @pytest.mark.asyncio
    async def test_sync_environmental_handles_400(self, test_session, test_settings):
        """Test that 400 errors are handled gracefully."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        client = AsyncMock()
        client.get_environmental_benefits.side_effect = APIError("Bad Request", status_code=400)

        strategy = EnvironmentalSyncStrategy(client, test_session, test_settings)
        count = await strategy.sync(12345)

        assert count == 0


class TestAlertSyncStrategy:
    """Test AlertSyncStrategy."""

    @pytest.mark.asyncio
    async def test_sync_alerts_handles_403(self, test_session, test_settings, mock_api_client):
        """Test that 403 errors are handled gracefully."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        strategy = AlertSyncStrategy(mock_api_client, test_session, test_settings)

        # mock_api_client.get_alerts raises 403
        count = await strategy.sync(12345)

        assert count == 0

    @pytest.mark.asyncio
    async def test_sync_alerts_success(self, test_session, test_settings):
        """Test successful alert sync."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        client = AsyncMock()
        client.get_alerts.return_value = [
            {
                "alertId": 1001,
                "severity": "HIGH",
                "alertCode": 100,
                "message": "Test alert",
                "alertTimestamp": "2024-01-15T12:00:00Z",
            }
        ]

        strategy = AlertSyncStrategy(client, test_session, test_settings)
        count = await strategy.sync(12345)

        assert count == 1


class TestInventorySyncStrategy:
    """Test InventorySyncStrategy."""

    @pytest.mark.asyncio
    async def test_sync_inventory(self, test_session, test_settings, mock_api_client):
        """Test syncing inventory."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        strategy = InventorySyncStrategy(mock_api_client, test_session, test_settings)

        count = await strategy.sync(12345)

        assert count >= 1
        mock_api_client.get_inventory.assert_called_once_with(12345)

    @pytest.mark.asyncio
    async def test_sync_inventory_empty(self, test_session, test_settings):
        """Test syncing when no inventory returned."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        client = AsyncMock()
        client.get_inventory.return_value = {}

        strategy = InventorySyncStrategy(client, test_session, test_settings)
        count = await strategy.sync(12345)

        assert count == 0


class TestBaseSyncStrategy:
    """Test BaseSyncStrategy common functionality."""

    def test_get_last_sync_no_metadata(self, test_session, test_settings, mock_api_client):
        """Test get_last_sync returns None when no metadata."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        strategy = EnergySyncStrategy(mock_api_client, test_session, test_settings)

        assert strategy.get_last_sync(12345) is None

    def test_get_start_time_full_sync(self, test_session, test_settings, mock_api_client):
        """Test get_start_time for full sync uses lookback."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        strategy = EnergySyncStrategy(mock_api_client, test_session, test_settings)

        start_time = strategy.get_start_time(12345, lookback_days=7)

        # Should be approximately 7 days ago
        days_ago = (datetime.now() - start_time).days
        assert 6 <= days_ago <= 8
