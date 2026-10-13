"""SolarEdge Monitoring API V2 client.

Authenticates with OAuth2 bearer tokens (see seh.api.auth), sends time ranges as UTC
ISO-8601 instants, and splits long ranges into the largest windows SolarEdge accepts for
each resolution (verified against the live API, 2026-10-12):

    QUARTER_HOUR: 1 week    HOUR: 24 hours    DAY: 1 month

Responses are returned as SolarEdge sends them (camelCase dicts); timestamps in responses
are ISO-8601 strings with the site's UTC offset, parsed with `parse_timestamp`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from seh.api.auth import OAuthTokenManager
from seh.api.rate_limiter import CreditLedger, RateLimiter
from seh.utils.exceptions import APIError, AuthenticationError, RateLimitError
from seh.utils.retry import retry_with_backoff

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seh.config.settings import Settings

logger = structlog.get_logger(__name__)

# Largest window per request, by resolution. DAY is documented as "1 month"; 28 days stays
# inside every calendar month.
MAX_WINDOW: dict[str, timedelta] = {
    "QUARTER_HOUR": timedelta(days=7),
    "HOUR": timedelta(hours=24),
    "DAY": timedelta(days=28),
}

DEVICE_TYPES = ("INVERTER", "BATTERY", "METER", "OPTIMIZER")
ALERTS_PAGE_SIZE = 100
# On HTTP 429, wait for Retry-After (if this short) and retry, at most this many times.
MAX_RATE_LIMIT_WAIT = 90.0
MAX_RATE_LIMIT_RETRIES = 2
MAX_ALERT_PAGES = 20

Params = list[tuple[str, str]]
TimePoint = date | datetime


def format_instant(value: TimePoint) -> str:
    """Format a time as a UTC instant ("2026-10-12T18:00:00Z").

    Naive datetimes are taken as this machine's local time, and dates as local midnight;
    seh runs in the site's timezone, as it did with V1.
    """
    return _as_aware(value).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timestamp(value: str) -> datetime:
    """Parse a V2 response timestamp (ISO-8601 with offset) into an aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def split_windows(
    start: TimePoint, end: TimePoint, resolution: str
) -> list[tuple[datetime, datetime]]:
    """Split [start, end) into consecutive windows no longer than the resolution allows."""
    start_dt = _as_aware(start)
    end_dt = _as_aware(end)
    if end_dt <= start_dt:
        return []
    step = MAX_WINDOW.get(resolution)
    if step is None:
        return [(start_dt, end_dt)]
    windows = []
    cursor = start_dt
    while cursor < end_dt:
        window_end = min(cursor + step, end_dt)
        windows.append((cursor, window_end))
        cursor = window_end
    return windows


def _as_aware(value: TimePoint) -> datetime:
    if not isinstance(value, datetime):
        value = datetime.combine(value, time.min)
    return value if value.tzinfo is not None else value.astimezone()


def _merge_values(target: dict[str, Any], values: list[Any]) -> None:
    """Add series points keyed by timestamp; a later window wins at a shared boundary."""
    for point in values:
        if isinstance(point, dict) and isinstance(point.get("timestamp"), str):
            target[point["timestamp"]] = point


def _sorted_values(points: dict[str, Any]) -> list[dict[str, Any]]:
    return [points[k] for k in sorted(points, key=parse_timestamp)]


class SolarEdgeClient:
    """Async client for the SolarEdge Monitoring API V2."""

    def __init__(
        self,
        settings: Settings,
        token_manager: OAuthTokenManager | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            settings: Application settings.
            token_manager: OAuth token source (defaults to the configured token file).
            transport: Optional httpx transport, for tests.
        """
        self._settings = settings
        self._base_url = settings.api_base_url.rstrip("/")
        self._timeout = settings.api_timeout
        self._auth = token_manager or OAuthTokenManager(settings)
        self._transport = transport
        self._rate_limiter = RateLimiter(
            max_concurrent=settings.api_max_concurrent,
            per_minute=settings.api_per_minute_limit,
            ledger=CreditLedger(settings.usage_path, settings.api_monthly_credits),
        )
        self._client: httpx.AsyncClient | None = None
        self._devices_cache: dict[tuple[int, tuple[str, ...]], list[dict[str, Any]]] = {}

    async def __aenter__(self) -> SolarEdgeClient:
        """Context manager entry; fails fast if OAuth credentials are not configured."""
        self._settings.require_oauth_credentials()
        self._client = httpx.AsyncClient(timeout=self._timeout, transport=self._transport)
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Context manager exit."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # --- transport -------------------------------------------------------------

    @retry_with_backoff(max_retries=3, base_delay=2.0)
    async def _request(self, path: str, params: Params | None = None) -> Any:
        """GET a V2 resource with bearer auth, refreshing the token once on HTTP 401.

        Raises:
            AuthenticationError: If the stored sign-in is missing or rejected.
            RateLimitError: If the monthly credit budget is spent, or on HTTP 429 when
                Retry-After is missing, too long, or keeps recurring.
            APIError: On any other failure (4xx errors are not retried).
        """
        if not self._client:
            raise APIError("Client not initialized. Use 'async with' context manager.")

        token = await self._auth.get_access_token()
        refreshed = False
        rate_limit_retries = 0
        while True:
            response = await self._send(path, params, token)
            if response.status_code == 401 and not refreshed:
                token = await self._auth.handle_unauthorized(token)
                refreshed = True
                continue
            if response.status_code == 429:
                wait = _retry_after(response)
                if (
                    rate_limit_retries < MAX_RATE_LIMIT_RETRIES
                    and wait is not None
                    and wait <= MAX_RATE_LIMIT_WAIT
                ):
                    rate_limit_retries += 1
                    logger.warning("SolarEdge rate limit hit; waiting", path=path, seconds=wait)
                    await asyncio.sleep(wait)
                    continue
            break

        if response.status_code == 401:
            raise AuthenticationError(
                f"SolarEdge rejected the access token for {path} even after a refresh. "
                "Run 'seh auth login' to sign in again."
            )
        if response.status_code == 429:
            raise RateLimitError(
                f"SolarEdge rate limit reached on {path}: {_problem_detail(response)}",
                retry_after=_retry_after(response),
            )
        if response.status_code >= 400:
            detail = _problem_detail(response)
            logger.error("API error", status_code=response.status_code, path=path, detail=detail)
            raise APIError(
                f"API request failed (HTTP {response.status_code}) for {path}: {detail}",
                status_code=response.status_code,
            )
        try:
            return response.json()
        except ValueError as e:
            raise APIError(f"Invalid JSON from {path}") from e

    async def _send(self, path: str, params: Params | None, token: str) -> httpx.Response:
        """Send one GET inside the rate limiter (each send costs one API credit)."""
        assert self._client is not None
        async with self._rate_limiter:
            logger.debug("API request", path=path)
            try:
                response = await self._client.get(
                    f"{self._base_url}{path}",
                    params=tuple(params or ()),
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
            except httpx.RequestError as e:
                logger.error("Request error", path=path, error=type(e).__name__)
                raise APIError(f"Request failed: {type(e).__name__}: {e}") from e
            self._rate_limiter.note_remaining_minute(
                response.headers.get("x-ratelimit-remaining-minute")
            )
        return response

    def credits_used(self) -> tuple[str, int] | None:
        """(month, API credits used this month) from the shared ledger."""
        return self._rate_limiter.credits_used()

    async def _series(
        self, path: str, start: TimePoint, end: TimePoint, resolution: str, unit: str
    ) -> list[dict[str, Any]]:
        """Fetch a {values: [...]} series across as many windows as needed."""
        points: dict[str, Any] = {}
        for window_start, window_end in split_windows(start, end, resolution):
            data = await self._request(
                path,
                [
                    ("resolution", resolution),
                    ("unit", unit),
                    ("from", format_instant(window_start)),
                    ("to", format_instant(window_end)),
                ],
            )
            if isinstance(data, dict):
                _merge_values(points, data.get("values") or [])
        return _sorted_values(points)

    async def _telemetry(
        self, path: str, key: str, start: TimePoint, end: TimePoint, resolution: str
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Fetch per-device telemetry across windows.

        Returns {serial: {metric: {"unit": str | None, "values": [{timestamp, value}]}}}.
        """
        merged: dict[str, dict[str, dict[str, Any]]] = {}
        for window_start, window_end in split_windows(start, end, resolution):
            data = await self._request(
                path,
                [
                    ("resolution", resolution),
                    ("from", format_instant(window_start)),
                    ("to", format_instant(window_end)),
                ],
            )
            devices = data.get(key) if isinstance(data, dict) else None
            if not isinstance(devices, dict):
                continue
            for serial, metrics in devices.items():
                if not isinstance(metrics, dict):
                    continue
                device = merged.setdefault(serial, {})
                for metric, series in metrics.items():
                    if not isinstance(series, dict):
                        continue
                    entry = device.setdefault(metric, {"unit": series.get("unit"), "points": {}})
                    _merge_values(entry["points"], series.get("values") or [])
        return {
            serial: {
                metric: {"unit": entry["unit"], "values": _sorted_values(entry["points"])}
                for metric, entry in metrics.items()
            }
            for serial, metrics in merged.items()
        }

    # --- sites -----------------------------------------------------------------

    async def get_sites(self) -> list[dict[str, Any]]:
        """Get the configured sites (OAuth Site Access cannot list sites; see SEH_SITE_IDS)."""
        return [await self.get_site(site_id) for site_id in self._settings.require_site_ids()]

    async def get_site(self, site_id: int) -> dict[str, Any]:
        """GET /sites/{id}: name, peak power, location (with timezone), activation status."""
        data = await self._request(f"/sites/{site_id}")
        return data if isinstance(data, dict) else {}

    async def get_overview(self, site_id: int) -> dict[str, Any]:
        """GET /sites/{id}/overview: today's production and consumption breakdown (Wh)."""
        data = await self._request(f"/sites/{site_id}/overview")
        return data if isinstance(data, dict) else {}

    async def get_devices(
        self, site_id: int, types: Sequence[str] = DEVICE_TYPES
    ) -> list[dict[str, Any]]:
        """GET /sites/{id}/devices for the given device types (inverters only if none given).

        Cached for the life of the client, so the equipment and inventory strategies share
        one API credit per sync.
        """
        key = (site_id, tuple(types))
        if key not in self._devices_cache:
            data = await self._request(f"/sites/{site_id}/devices", [("types", t) for t in types])
            self._devices_cache[key] = (
                [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []
            )
        return [dict(d) for d in self._devices_cache[key]]

    async def get_environmental_benefits(self, site_id: int) -> dict[str, Any]:
        """GET /sites/{id}/environmental-benefits: co2Emissions, evMiles, unit."""
        data = await self._request(f"/sites/{site_id}/environmental-benefits")
        return data if isinstance(data, dict) else {}

    async def get_alerts(self, site_id: int) -> list[dict[str, Any]]:
        """GET /sites/{id}/alerts, all pages."""
        alerts: list[dict[str, Any]] = []
        for page in range(1, MAX_ALERT_PAGES + 1):
            data = await self._request(
                f"/sites/{site_id}/alerts",
                [("page", str(page)), ("alerts-in-page", str(ALERTS_PAGE_SIZE))],
            )
            batch = [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []
            alerts.extend(batch)
            if len(batch) < ALERTS_PAGE_SIZE:
                break
        return alerts

    # --- energy and power ------------------------------------------------------

    async def get_energy(
        self, site_id: int, start: TimePoint, end: TimePoint, resolution: str = "DAY"
    ) -> list[dict[str, Any]]:
        """Energy in Wh per interval: [{"timestamp", "value"}]. Values may be None."""
        return await self._series(f"/sites/{site_id}/energy", start, end, resolution, "WH")

    async def get_power(
        self, site_id: int, start: TimePoint, end: TimePoint, resolution: str = "QUARTER_HOUR"
    ) -> list[dict[str, Any]]:
        """Average power in W per interval: [{"timestamp", "value"}]. Values may be None."""
        return await self._series(f"/sites/{site_id}/power", start, end, resolution, "W")

    async def get_power_flow(self, site_id: int) -> dict[str, Any]:
        """GET /sites/{id}/power-flow: current pv/load/grid/storage snapshot (kW)."""
        data = await self._request(f"/sites/{site_id}/power-flow")
        return data if isinstance(data, dict) else {}

    # --- telemetry -------------------------------------------------------------

    async def get_meters_telemetry(
        self, site_id: int, start: TimePoint, end: TimePoint, resolution: str = "QUARTER_HOUR"
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Per-meter production/import/export power (W) and energy (Wh)."""
        return await self._telemetry(
            f"/sites/{site_id}/meters/telemetry", "meters", start, end, resolution
        )

    async def get_inverters_telemetry(
        self, site_id: int, start: TimePoint, end: TimePoint, resolution: str = "QUARTER_HOUR"
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Per-inverter power, energy, consumedAcPower/Energy, voltage, current, frequency."""
        return await self._telemetry(
            f"/sites/{site_id}/inverters/telemetry", "inverters", start, end, resolution
        )

    async def get_storage_telemetry(
        self, site_id: int, start: TimePoint, end: TimePoint, resolution: str = "QUARTER_HOUR"
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Per-battery telemetry; empty when the site has no battery."""
        return await self._telemetry(
            f"/sites/{site_id}/storage/telemetry", "storage", start, end, resolution
        )


def _problem_detail(response: httpx.Response) -> str:
    """Short description from an RFC 7807 problem response (never includes request auth)."""
    try:
        data = response.json()
    except ValueError:
        return response.reason_phrase or "error"
    if isinstance(data, dict):
        for key in ("detail", "title", "message", "error"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value[:300]
    return response.reason_phrase or "error"


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
