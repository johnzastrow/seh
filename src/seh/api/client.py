"""SolarEdge API client."""

from datetime import date, datetime
from typing import Any

import httpx
import structlog

from seh.api.rate_limiter import RateLimiter
from seh.config.settings import Settings
from seh.utils.exceptions import APIError
from seh.utils.retry import retry_with_backoff

logger = structlog.get_logger(__name__)


class SolarEdgeClient:
    """Async client for the SolarEdge Monitoring API."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the client.

        Args:
            settings: Application settings.
        """
        self._settings = settings
        self._base_url = settings.api_base_url.rstrip("/")
        self._api_key = settings.api_key.get_secret_value()
        self._timeout = settings.api_timeout
        self._rate_limiter = RateLimiter(
            max_concurrent=settings.api_max_concurrent,
            daily_limit=settings.api_daily_limit,
        )
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "SolarEdgeClient":
        """Context manager entry."""
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Context manager exit."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _format_date(self, d: date | datetime | None) -> str | None:
        """Format a date for the API.

        Args:
            d: Date to format.

        Returns:
            Formatted date string or None.
        """
        if d is None:
            return None
        if isinstance(d, datetime):
            return d.strftime("%Y-%m-%d %H:%M:%S")
        return d.strftime("%Y-%m-%d")

    @retry_with_backoff(max_retries=3, base_delay=2.0)
    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an API request.

        Args:
            method: HTTP method.
            path: API path.
            params: Query parameters.

        Returns:
            JSON response data.

        Raises:
            APIError: If the request fails.
        """
        if not self._client:
            raise APIError("Client not initialized. Use 'async with' context manager.")

        url = f"{self._base_url}{path}"
        params = params or {}
        params["api_key"] = self._api_key

        async with self._rate_limiter:
            logger.debug("API request", method=method, path=path)

            try:
                response = await self._client.request(method, url, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "API error",
                    status_code=e.response.status_code,
                    url=url,
                    response=e.response.text[:500],
                )
                raise APIError(
                    f"API request failed: {e.response.text[:200]}",
                    status_code=e.response.status_code,
                ) from e
            except httpx.RequestError as e:
                logger.error("Request error", url=url, error=str(e))
                raise APIError(f"Request failed: {e}") from e

    # Site endpoints

    async def get_sites(self) -> list[dict[str, Any]]:
        """Get list of sites for the account.

        Returns:
            List of site data dictionaries.
        """
        data = await self._request("GET", "/sites/list")
        sites = data.get("sites", {}).get("site", [])
        # Ensure it's a list (single site returns dict)
        if isinstance(sites, dict):
            sites = [sites]
        return sites

    async def get_site_details(self, site_id: int) -> dict[str, Any]:
        """Get detailed information for a site.

        Args:
            site_id: Site ID.

        Returns:
            Site details dictionary.
        """
        data = await self._request("GET", f"/site/{site_id}/details")
        return data.get("details", {})

    # Equipment endpoints

    async def get_equipment(self, site_id: int) -> list[dict[str, Any]]:
        """Get list of equipment at a site.

        Args:
            site_id: Site ID.

        Returns:
            List of equipment (inverters).
        """
        data = await self._request("GET", f"/equipment/{site_id}/list")
        reporters = data.get("reporters", {}).get("list", [])
        if isinstance(reporters, dict):
            reporters = [reporters]
        return reporters

    async def get_inverter_data(
        self,
        site_id: int,
        serial_number: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        """Get inverter telemetry data.

        Args:
            site_id: Site ID.
            serial_number: Inverter serial number.
            start_time: Start time.
            end_time: End time.

        Returns:
            List of telemetry readings.
        """
        data = await self._request(
            "GET",
            f"/equipment/{site_id}/{serial_number}/data",
            params={
                "startTime": self._format_date(start_time),
                "endTime": self._format_date(end_time),
            },
        )
        return data.get("data", {}).get("telemetries", [])

    # Energy endpoints

    async def get_energy(
        self,
        site_id: int,
        start_date: date,
        end_date: date,
        time_unit: str = "DAY",
    ) -> list[dict[str, Any]]:
        """Get energy production data.

        Args:
            site_id: Site ID.
            start_date: Start date.
            end_date: End date.
            time_unit: Time unit (DAY, WEEK, MONTH, YEAR).

        Returns:
            List of energy values.
        """
        data = await self._request(
            "GET",
            f"/site/{site_id}/energy",
            params={
                "startDate": self._format_date(start_date),
                "endDate": self._format_date(end_date),
                "timeUnit": time_unit,
            },
        )
        return data.get("energy", {}).get("values", [])

    async def get_energy_details(
        self,
        site_id: int,
        start_time: datetime,
        end_time: datetime,
        time_unit: str = "QUARTER_OF_AN_HOUR",
    ) -> dict[str, Any]:
        """Get detailed energy data.

        Args:
            site_id: Site ID.
            start_time: Start time.
            end_time: End time.
            time_unit: Time unit (QUARTER_OF_AN_HOUR, HOUR, DAY, WEEK, MONTH, YEAR).

        Returns:
            Energy details dictionary.
        """
        data = await self._request(
            "GET",
            f"/site/{site_id}/energyDetails",
            params={
                "startTime": self._format_date(start_time),
                "endTime": self._format_date(end_time),
                "timeUnit": time_unit,
            },
        )
        return data.get("energyDetails", {})

    # Power endpoints

    async def get_power(
        self,
        site_id: int,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        """Get power production data.

        Args:
            site_id: Site ID.
            start_time: Start time.
            end_time: End time.

        Returns:
            List of power values.
        """
        data = await self._request(
            "GET",
            f"/site/{site_id}/power",
            params={
                "startTime": self._format_date(start_time),
                "endTime": self._format_date(end_time),
            },
        )
        return data.get("power", {}).get("values", [])

    async def get_power_details(
        self,
        site_id: int,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, Any]:
        """Get detailed power data.

        Args:
            site_id: Site ID.
            start_time: Start time.
            end_time: End time.

        Returns:
            Power details dictionary.
        """
        data = await self._request(
            "GET",
            f"/site/{site_id}/powerDetails",
            params={
                "startTime": self._format_date(start_time),
                "endTime": self._format_date(end_time),
            },
        )
        return data.get("powerDetails", {})

    async def get_power_flow(self, site_id: int) -> dict[str, Any]:
        """Get current power flow.

        Args:
            site_id: Site ID.

        Returns:
            Power flow dictionary.
        """
        data = await self._request("GET", f"/site/{site_id}/currentPowerFlow")
        return data.get("siteCurrentPowerFlow", {})

    # Storage endpoints

    async def get_storage_data(
        self,
        site_id: int,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, Any]:
        """Get storage (battery) data.

        Args:
            site_id: Site ID.
            start_time: Start time.
            end_time: End time.

        Returns:
            Storage data dictionary.
        """
        data = await self._request(
            "GET",
            f"/site/{site_id}/storageData",
            params={
                "startTime": self._format_date(start_time),
                "endTime": self._format_date(end_time),
            },
        )
        return data.get("storageData", {})

    # Meter endpoints

    async def get_meters(self, site_id: int) -> list[dict[str, Any]]:
        """Get list of meters at a site.

        Args:
            site_id: Site ID.

        Returns:
            List of meter info.
        """
        data = await self._request("GET", f"/site/{site_id}/meters")
        meters = data.get("metersList", {}).get("meters", [])
        if isinstance(meters, dict):
            meters = [meters]
        return meters

    async def get_meter_data(
        self,
        site_id: int,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, Any]:
        """Get meter readings.

        Args:
            site_id: Site ID.
            start_time: Start time.
            end_time: End time.

        Returns:
            Meter data dictionary.
        """
        data = await self._request(
            "GET",
            f"/site/{site_id}/meters",
            params={
                "startTime": self._format_date(start_time),
                "endTime": self._format_date(end_time),
            },
        )
        return data.get("meterEnergyDetails", {})

    # Environmental benefits endpoints

    async def get_environmental_benefits(self, site_id: int) -> dict[str, Any]:
        """Get environmental benefits data for a site.

        Args:
            site_id: Site ID.

        Returns:
            Environmental benefits dictionary with CO2 saved, trees planted, etc.
        """
        data = await self._request("GET", f"/site/{site_id}/envBenefits")
        return data.get("envBenefits", {})

    # Alert endpoints

    async def get_alerts(self, site_id: int) -> list[dict[str, Any]]:
        """Get alerts for a site.

        Args:
            site_id: Site ID.

        Returns:
            List of alert dictionaries.
        """
        data = await self._request("GET", f"/site/{site_id}/alerts")
        alerts = data.get("alerts", {}).get("alert", [])
        if isinstance(alerts, dict):
            alerts = [alerts]
        return alerts

    # Inventory endpoints

    async def get_inventory(self, site_id: int) -> dict[str, Any]:
        """Get inventory for a site.

        Args:
            site_id: Site ID.

        Returns:
            Inventory dictionary with inverters, optimizers, etc.
        """
        data = await self._request("GET", f"/site/{site_id}/inventory")
        return data.get("Inventory", {})

    # Utility methods

    @property
    def remaining_requests(self) -> int:
        """Get remaining API requests for today."""
        return self._rate_limiter.remaining_requests

    @property
    def requests_today(self) -> int:
        """Get number of requests made today."""
        return self._rate_limiter.requests_today
