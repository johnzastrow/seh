"""Tests for the SolarEdge Monitoring API V2 client."""

from datetime import UTC, date, datetime, timedelta, timezone
from itertools import pairwise
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from seh.api import client as client_module
from seh.api.client import (
    SolarEdgeClient,
    format_instant,
    parse_timestamp,
    split_windows,
)
from seh.config.settings import Settings
from seh.utils.exceptions import APIError, AuthenticationError, ConfigurationError, RateLimitError

EDT = timezone(timedelta(hours=-4))
BASE = "https://monitoringapi.solaredge.com/v2"


class FakeAuth:
    """Stands in for OAuthTokenManager."""

    def __init__(self) -> None:
        self.token = "token-1"
        self.refreshes = 0

    async def get_access_token(self) -> str:
        return self.token

    async def handle_unauthorized(self, rejected: str) -> str:
        self.refreshes += 1
        self.token = f"token-{self.refreshes + 1}"
        return self.token


class Api:
    """Scripted MockTransport handler: responses are popped per request."""

    def __init__(self, *responses: httpx.Response | dict | list) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        nxt = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return nxt if isinstance(nxt, httpx.Response) else httpx.Response(200, json=nxt)

    def params(self, index: int = 0) -> dict[str, list[str]]:
        return parse_qs(urlparse(str(self.requests[index].url)).query)

    def path(self, index: int = 0) -> str:
        return self.requests[index].url.path


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    for var in ("SEH_OAUTH_CLIENT_ID", "SEH_OAUTH_CLIENT_SECRET", "SEH_SITE_IDS"):
        monkeypatch.delenv(var, raising=False)
    return Settings(
        _env_file=None,
        oauth_client_id="id",
        oauth_client_secret="secret",
        site_ids="111,222",
        token_file=str(tmp_path / "tokens.json"),
    )


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    """Retries back off with asyncio.sleep; skip the waiting in tests."""

    async def instant(_seconds):
        return None

    monkeypatch.setattr("seh.utils.retry.asyncio.sleep", instant)


def make_client(settings, api: Api, auth: FakeAuth | None = None) -> SolarEdgeClient:
    return SolarEdgeClient(
        settings, token_manager=auth or FakeAuth(), transport=httpx.MockTransport(api)
    )


def series(*points: tuple[str, float | None]) -> dict:
    return {"unit": "W", "values": [{"timestamp": t, "value": v} for t, v in points]}


class TestTimeHelpers:
    def test_format_instant_converts_aware_time_to_utc(self):
        assert format_instant(datetime(2026, 10, 12, 14, 0, tzinfo=EDT)) == "2026-10-12T18:00:00Z"

    def test_format_instant_treats_naive_time_as_local(self):
        naive = datetime(2026, 10, 12, 14, 0)
        expected = naive.astimezone().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert format_instant(naive) == expected

    def test_format_instant_treats_date_as_local_midnight(self):
        expected = (
            datetime(2026, 10, 12).astimezone().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        assert format_instant(date(2026, 10, 12)) == expected

    def test_parse_timestamp_keeps_offset(self):
        parsed = parse_timestamp("2026-10-12T06:00:00-04:00")
        assert parsed == datetime(2026, 10, 12, 6, 0, tzinfo=EDT)
        assert parse_timestamp("2026-10-12T10:00:00Z") == parsed

    @pytest.mark.parametrize(
        ("resolution", "span", "expected_windows"),
        [
            ("QUARTER_HOUR", timedelta(days=20), 3),
            ("QUARTER_HOUR", timedelta(days=7), 1),
            ("HOUR", timedelta(hours=30), 2),
            ("DAY", timedelta(days=365), 14),
            ("YEAR", timedelta(days=3000), 1),
        ],
    )
    def test_split_windows_respects_limits(self, resolution, span, expected_windows):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        windows = split_windows(start, start + span, resolution)

        assert len(windows) == expected_windows
        assert windows[0][0] == start
        assert windows[-1][1] == start + span
        for (_, prev_end), (next_start, _) in pairwise(windows):
            assert prev_end == next_start  # contiguous, no gaps
        limit = client_module.MAX_WINDOW.get(resolution)
        if limit:
            assert all(end - begin <= limit for begin, end in windows)

    def test_split_windows_empty_range(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        assert split_windows(start, start, "DAY") == []


class TestRequest:
    async def test_requires_oauth_credentials(self, settings):
        settings.oauth_client_secret = None
        with pytest.raises(ConfigurationError):
            async with make_client(settings, Api({})):
                pass

    async def test_request_without_context_manager_raises(self, settings):
        with pytest.raises(APIError, match="not initialized"):
            await make_client(settings, Api({})).get_site(111)

    async def test_sends_bearer_token_to_v2_path(self, settings):
        api = Api({"siteId": 111, "name": "Home"})
        async with make_client(settings, api) as client:
            site = await client.get_site(111)

        assert site["name"] == "Home"
        assert str(api.requests[0].url) == f"{BASE}/sites/111"
        assert api.requests[0].headers["authorization"] == "Bearer token-1"
        assert "api_key" not in str(api.requests[0].url)

    async def test_401_refreshes_token_once_and_retries(self, settings):
        auth = FakeAuth()
        api = Api(httpx.Response(401, json={"title": "Unauthorized"}), {"siteId": 111})
        async with make_client(settings, api, auth) as client:
            await client.get_site(111)

        assert auth.refreshes == 1
        assert [r.headers["authorization"] for r in api.requests] == [
            "Bearer token-1",
            "Bearer token-2",
        ]

    async def test_repeated_401_raises_authentication_error(self, settings):
        api = Api(httpx.Response(401, json={"title": "Unauthorized"}))
        async with make_client(settings, api) as client:
            with pytest.raises(AuthenticationError, match="seh auth login"):
                await client.get_site(111)
        assert len(api.requests) == 2

    async def test_403_is_not_retried(self, settings):
        api = Api(httpx.Response(403, json={"title": "Authorization Failed"}))
        async with make_client(settings, api) as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_power_flow(111)

        assert exc_info.value.status_code == 403
        assert "Authorization Failed" in str(exc_info.value)
        assert len(api.requests) == 1

    async def test_server_errors_are_retried(self, settings):
        api = Api(
            httpx.Response(503, json={"title": "Scheduled window"}),
            httpx.Response(503, json={"title": "Scheduled window"}),
            {"siteId": 111},
        )
        async with make_client(settings, api) as client:
            assert (await client.get_site(111))["siteId"] == 111
        assert len(api.requests) == 3

    async def test_429_waits_for_retry_after_then_succeeds(self, settings, monkeypatch):
        waits = []

        async def fake_sleep(seconds):
            waits.append(seconds)

        monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)
        api = Api(httpx.Response(429, headers={"retry-after": "42"}, json={}), {"siteId": 111})
        async with make_client(settings, api) as client:
            assert (await client.get_site(111))["siteId"] == 111
        assert waits == [42.0]
        assert len(api.requests) == 2

    async def test_429_gives_up_after_repeated_limits(self, settings):
        api = Api(httpx.Response(429, headers={"retry-after": "5"}, json={"title": "Too Many"}))
        async with make_client(settings, api) as client:
            with pytest.raises(RateLimitError) as exc_info:
                await client.get_site(111)
        assert exc_info.value.retry_after == 5.0
        assert len(api.requests) == 3  # first try + 2 retries

    @pytest.mark.parametrize("headers", [{}, {"retry-after": "600"}])
    async def test_429_without_short_retry_after_raises_immediately(self, settings, headers):
        api = Api(httpx.Response(429, headers=headers, json={"title": "Too Many"}))
        async with make_client(settings, api) as client:
            with pytest.raises(RateLimitError):
                await client.get_site(111)
        assert len(api.requests) == 1

    async def test_each_request_is_charged_to_the_credit_ledger(self, settings):
        api = Api(httpx.Response(401, json={}), {"siteId": 111})
        async with make_client(settings, api) as client:
            await client.get_site(111)
            _month, used = client.credits_used()
        assert used == 2  # the rejected attempt was sent, so it counts

    async def test_exhausted_budget_blocks_requests_before_sending(self, settings):
        settings.api_monthly_credits = 1
        api = Api({"siteId": 111})
        async with make_client(settings, api) as client:
            await client.get_site(111)
            with pytest.raises(RateLimitError, match="credit budget"):
                await client.get_site(111)
        assert len(api.requests) == 1

    async def test_bad_request_detail_is_reported(self, settings):
        detail = "resolution=QUARTER_HOUR supports a maximum window of 1 week"
        api = Api(httpx.Response(400, json={"title": "Bad request", "detail": detail}))
        async with make_client(settings, api) as client:
            with pytest.raises(APIError, match="maximum window of 1 week"):
                await client.get_overview(111)


class TestEndpoints:
    async def test_get_sites_reads_configured_site_ids(self, settings):
        api = Api({"siteId": 111}, {"siteId": 222})
        async with make_client(settings, api) as client:
            sites = await client.get_sites()

        assert [s["siteId"] for s in sites] == [111, 222]
        assert [api.path(i) for i in range(2)] == ["/v2/sites/111", "/v2/sites/222"]

    async def test_get_power_splits_long_range_and_merges_values(self, settings):
        start = datetime(2026, 10, 1, tzinfo=UTC)
        end = start + timedelta(days=10)
        api = Api(
            series(("2026-10-01T00:00:00Z", 1.0), ("2026-10-08T00:00:00Z", 2.0)),
            series(("2026-10-08T00:00:00Z", 3.0), ("2026-10-09T00:00:00Z", None)),
        )
        async with make_client(settings, api) as client:
            values = await client.get_power(111, start, end)

        assert len(api.requests) == 2
        first, second = api.params(0), api.params(1)
        assert first["resolution"] == ["QUARTER_HOUR"]
        assert first["unit"] == ["W"]
        assert first["from"] == ["2026-10-01T00:00:00Z"]
        assert first["to"] == second["from"] == ["2026-10-08T00:00:00Z"]
        assert second["to"] == ["2026-10-11T00:00:00Z"]
        # Boundary point de-duplicated (later window wins); order by time; None kept.
        assert [(v["timestamp"], v["value"]) for v in values] == [
            ("2026-10-01T00:00:00Z", 1.0),
            ("2026-10-08T00:00:00Z", 3.0),
            ("2026-10-09T00:00:00Z", None),
        ]

    async def test_get_energy_uses_day_resolution_in_wh(self, settings):
        api = Api(series(("2026-10-05T00:00:00-04:00", 4.0)))
        async with make_client(settings, api) as client:
            values = await client.get_energy(111, date(2026, 10, 5), date(2026, 10, 6))

        assert api.path() == "/v2/sites/111/energy"
        assert api.params()["resolution"] == ["DAY"]
        assert api.params()["unit"] == ["WH"]
        assert values[0]["value"] == 4.0

    async def test_get_meters_telemetry_merges_devices_across_windows(self, settings):
        def window(ts: str, value: float) -> dict:
            return {
                "period": {},
                "resolution": "QUARTER_HOUR",
                "meters": {"M1": {"importPower": series((ts, value))}},
            }

        start = datetime(2026, 10, 1, tzinfo=UTC)
        api = Api(window("2026-10-01T00:00:00Z", 10.0), window("2026-10-09T00:00:00Z", 20.0))
        async with make_client(settings, api) as client:
            meters = await client.get_meters_telemetry(111, start, start + timedelta(days=9))

        assert api.path() == "/v2/sites/111/meters/telemetry"
        assert "unit" not in api.params()  # telemetry takes no unit parameter
        import_power = meters["M1"]["importPower"]
        assert import_power["unit"] == "W"
        assert [v["value"] for v in import_power["values"]] == [10.0, 20.0]

    async def test_get_inverters_telemetry_reads_inverters_key(self, settings):
        api = Api({"inverters": {"INV1": {"voltage": series(("2026-10-01T00:00:00Z", 240.0))}}})
        start = datetime(2026, 10, 1, tzinfo=UTC)
        async with make_client(settings, api) as client:
            data = await client.get_inverters_telemetry(111, start, start + timedelta(hours=12))
        assert data["INV1"]["voltage"]["values"][0]["value"] == 240.0

    async def test_get_storage_telemetry_without_battery_is_empty(self, settings):
        api = Api({"period": {}, "resolution": "QUARTER_HOUR", "storage": {}})
        start = datetime(2026, 10, 1, tzinfo=UTC)
        async with make_client(settings, api) as client:
            assert await client.get_storage_telemetry(111, start, start + timedelta(hours=1)) == {}

    async def test_get_devices_sends_each_type(self, settings):
        api = Api([{"type": "INVERTER", "serialNumber": "S1"}, "junk"])
        async with make_client(settings, api) as client:
            devices = await client.get_devices(111)

        assert api.params()["types"] == ["INVERTER", "BATTERY", "METER", "OPTIMIZER"]
        assert devices == [{"type": "INVERTER", "serialNumber": "S1"}]

    async def test_get_alerts_follows_pages(self, settings):
        full_page = [{"alertId": i} for i in range(100)]
        api = Api(full_page, [{"alertId": 100}])
        async with make_client(settings, api) as client:
            alerts = await client.get_alerts(111)

        assert len(alerts) == 101
        assert [api.params(i)["page"] for i in range(2)] == [["1"], ["2"]]

    async def test_simple_endpoints_use_v2_paths(self, settings):
        api = Api({"ok": True})
        async with make_client(settings, api) as client:
            await client.get_overview(111)
            await client.get_power_flow(111)
            await client.get_environmental_benefits(111)
        assert [api.path(i) for i in range(3)] == [
            "/v2/sites/111/overview",
            "/v2/sites/111/power-flow",
            "/v2/sites/111/environmental-benefits",
        ]
