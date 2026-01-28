"""Tests for SolarEdge API client."""

from datetime import datetime, date
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import httpx

from seh.api.client import SolarEdgeClient
from seh.api.rate_limiter import RateLimiter
from seh.utils.exceptions import APIError


class TestSolarEdgeClient:
    """Test SolarEdgeClient."""

    @pytest.fixture
    def client(self, test_settings):
        """Create a test client."""
        return SolarEdgeClient(test_settings)

    def test_client_initialization(self, client, test_settings):
        """Test client initializes correctly."""
        assert client._api_key == test_settings.api_key.get_secret_value()
        assert client._timeout == test_settings.api_timeout
        assert client._rate_limiter is not None

    def test_format_date_with_date(self, client):
        """Test _format_date with date object."""
        d = date(2024, 1, 15)
        assert client._format_date(d) == "2024-01-15"

    def test_format_date_with_datetime(self, client):
        """Test _format_date with datetime object."""
        dt = datetime(2024, 1, 15, 12, 30, 45)
        assert client._format_date(dt) == "2024-01-15 12:30:45"

    def test_format_date_with_none(self, client):
        """Test _format_date with None."""
        assert client._format_date(None) is None

    @pytest.mark.asyncio
    async def test_context_manager(self, client):
        """Test client context manager."""
        async with client as c:
            assert c._client is not None
        assert c._client is None

    @pytest.mark.asyncio
    async def test_request_without_context_manager_raises(self, client):
        """Test that request without context manager raises error."""
        with pytest.raises(APIError, match="Client not initialized"):
            await client._request("GET", "/test")


class TestSolarEdgeClientMocked:
    """Test SolarEdgeClient with mocked HTTP responses."""

    @pytest.fixture
    def mock_response(self):
        """Create mock HTTP response."""
        response = MagicMock()
        response.json.return_value = {
            "sites": {"site": [{"id": 12345, "name": "Test Site"}]}
        }
        response.raise_for_status = MagicMock()
        return response

    @pytest.mark.asyncio
    async def test_get_sites(self, test_settings, mock_response):
        """Test get_sites returns site list."""
        client = SolarEdgeClient(test_settings)

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "sites": {"site": [{"id": 12345, "name": "Test Site"}]}
            }

            async with client:
                sites = await client.get_sites()

            assert len(sites) == 1
            assert sites[0]["id"] == 12345
            assert sites[0]["name"] == "Test Site"

    @pytest.mark.asyncio
    async def test_get_sites_single_site_as_dict(self, test_settings):
        """Test get_sites handles single site returned as dict."""
        client = SolarEdgeClient(test_settings)

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            # API returns single site as dict, not list
            mock_request.return_value = {
                "sites": {"site": {"id": 12345, "name": "Single Site"}}
            }

            async with client:
                sites = await client.get_sites()

            assert len(sites) == 1
            assert sites[0]["name"] == "Single Site"

    @pytest.mark.asyncio
    async def test_get_site_details(self, test_settings):
        """Test get_site_details returns site details."""
        client = SolarEdgeClient(test_settings)

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "details": {
                    "name": "Test Site",
                    "status": "Active",
                    "peakPower": 10.5,
                }
            }

            async with client:
                details = await client.get_site_details(12345)

            assert details["name"] == "Test Site"
            assert details["status"] == "Active"
            mock_request.assert_called_once_with("GET", "/site/12345/details")

    @pytest.mark.asyncio
    async def test_get_energy(self, test_settings):
        """Test get_energy returns energy values."""
        client = SolarEdgeClient(test_settings)

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "energy": {
                    "values": [
                        {"date": "2024-01-01", "value": 25000},
                        {"date": "2024-01-02", "value": 28000},
                    ]
                }
            }

            async with client:
                energy = await client.get_energy(
                    12345,
                    date(2024, 1, 1),
                    date(2024, 1, 2),
                )

            assert len(energy) == 2
            assert energy[0]["value"] == 25000

    @pytest.mark.asyncio
    async def test_get_power(self, test_settings):
        """Test get_power returns power values."""
        client = SolarEdgeClient(test_settings)

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "power": {
                    "values": [
                        {"date": "2024-01-15 12:00:00", "value": 5000},
                    ]
                }
            }

            async with client:
                power = await client.get_power(
                    12345,
                    datetime(2024, 1, 15, 12, 0),
                    datetime(2024, 1, 15, 13, 0),
                )

            assert len(power) == 1
            assert power[0]["value"] == 5000

    @pytest.mark.asyncio
    async def test_get_environmental_benefits(self, test_settings):
        """Test get_environmental_benefits returns benefits data."""
        client = SolarEdgeClient(test_settings)

        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "envBenefits": {
                    "treesPlanted": 10.5,
                    "gasEmissionSaved": {"co2": 500.0, "units": "KG"},
                }
            }

            async with client:
                benefits = await client.get_environmental_benefits(12345)

            assert benefits["treesPlanted"] == 10.5
            assert benefits["gasEmissionSaved"]["co2"] == 500.0


class TestRateLimiter:
    """Test RateLimiter."""

    def test_rate_limiter_initialization(self):
        """Test rate limiter initializes correctly."""
        limiter = RateLimiter(max_concurrent=3, daily_limit=300)
        assert limiter.remaining_requests == 300
        assert limiter.requests_today == 0

    @pytest.mark.asyncio
    async def test_rate_limiter_tracks_requests(self):
        """Test rate limiter tracks request count."""
        limiter = RateLimiter(max_concurrent=3, daily_limit=300)

        async with limiter:
            pass

        assert limiter.requests_today == 1
        assert limiter.remaining_requests == 299

    @pytest.mark.asyncio
    async def test_rate_limiter_daily_limit(self):
        """Test rate limiter enforces daily limit."""
        from seh.utils.exceptions import RateLimitError

        limiter = RateLimiter(max_concurrent=3, daily_limit=2)

        # Use up the limit
        async with limiter:
            pass
        async with limiter:
            pass

        # Next request should fail
        with pytest.raises(RateLimitError, match="Daily API limit"):
            async with limiter:
                pass
