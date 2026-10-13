"""Tests for sync strategies not yet migrated to API V2 (energy, base).

V2 strategy tests live in test_sync_strategies_v2.py.
"""

from datetime import datetime

import pytest

from seh.db.models import Site
from seh.sync.strategies.energy import EnergySyncStrategy


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
