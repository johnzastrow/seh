"""Tests for 'seh api get' and SolarEdgeClient.get_raw path validation."""

import json
import os
from typing import ClassVar

import httpx
import pytest
from click.testing import CliRunner

import seh.api.client as client_module
from seh.api.client import SolarEdgeClient, validate_raw_path
from seh.cli import cli
from seh.config.settings import Settings
from seh.utils.exceptions import APIError


class TestValidateRawPath:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("/sites/123", "/sites/123"),
            ("sites/123/alerts", "/sites/123/alerts"),
            ("  /sites/123/meters/telemetry ", "/sites/123/meters/telemetry"),
            ("/sites/123/power-flow", "/sites/123/power-flow"),
        ],
    )
    def test_accepts_relative_api_paths(self, given, expected):
        assert validate_raw_path(given) == expected

    @pytest.mark.parametrize(
        "bad",
        [
            "https://evil.example/steal",  # full URL: token must never leave the API host
            "//evil.example/x",
            "/sites/../../oauth2/token",
            "/sites/123?api_key=x",  # query belongs in --param
            "/sites/123 /x",
            "/sites/%2e%2e/x",
            "/sites/123#frag",
        ],
    )
    def test_rejects_anything_else(self, bad):
        with pytest.raises(ValueError, match="Invalid API path"):
            validate_raw_path(bad)


class FakeClient:
    """Records get_raw calls; returns canned JSON or raises."""

    calls: ClassVar[list] = []
    response: ClassVar[object] = {"siteId": 4242, "name": "Home"}
    error: ClassVar[Exception | None] = None

    def __init__(self, settings):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get_raw(self, path, params):
        FakeClient.calls.append((path, params))
        if FakeClient.error:
            raise FakeClient.error
        return FakeClient.response

    def credits_used(self):
        return ("2026-10", 202)


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEH_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("SEH_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("SEH_SITE_IDS", "4242,5555")
    monkeypatch.setenv("SEH_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.delenv("SEH_LOG_FILE", raising=False)
    monkeypatch.setattr(client_module, "SolarEdgeClient", FakeClient)
    FakeClient.calls = []
    FakeClient.response = {"siteId": 4242, "name": "Home"}
    FakeClient.error = None
    return tmp_path


def run(*args):
    return CliRunner().invoke(cli, ["api", "get", *args])


class TestApiGetCommand:
    def test_prints_raw_json_and_substitutes_site(self, cli_env):
        result = run("/sites/{site}", "-p", "a=1", "-p", "types=METER", "-p", "types=BATTERY")

        assert result.exit_code == 0, result.output
        assert FakeClient.calls == [
            ("/sites/4242", [("a", "1"), ("types", "METER"), ("types", "BATTERY")])
        ]
        assert json.loads(result.stdout) == {"siteId": 4242, "name": "Home"}
        assert "1 API credit used (202 this month" in result.stderr

    def test_site_option_overrides_default(self, cli_env):
        assert run("/sites/{site}/alerts", "--site", "5555").exit_code == 0
        assert FakeClient.calls[0][0] == "/sites/5555/alerts"

    def test_param_values_may_contain_equals(self, cli_env):
        run("/sites/{site}/power", "-p", "from=2026-10-12T00:00:00Z", "-p", "x=a=b")
        assert FakeClient.calls[0][1] == [("from", "2026-10-12T00:00:00Z"), ("x", "a=b")]

    def test_malformed_param_is_rejected(self, cli_env):
        result = run("/sites/{site}", "-p", "novalue")
        assert result.exit_code == 2
        assert FakeClient.calls == []

    def test_url_path_is_rejected_before_any_request(self, cli_env):
        result = run("https://evil.example/x")
        assert result.exit_code == 2
        assert "Invalid API path" in result.stderr
        assert FakeClient.calls == []

    def test_api_error_exits_1(self, cli_env):
        FakeClient.error = APIError("API request failed (HTTP 404): Unknown endpoint", 404)
        result = run("/sites/{site}/power/live")
        assert result.exit_code == 1
        assert "Unknown endpoint" in result.stderr

    def test_output_file_is_owner_only(self, cli_env):
        result = run("/sites/{site}", "-o", "site.json")
        assert result.exit_code == 0, result.output
        out = cli_env / "site.json"
        assert json.loads(out.read_text(encoding="utf-8"))["siteId"] == 4242
        assert result.stdout == ""
        if os.name == "posix":
            assert out.stat().st_mode & 0o777 == 0o600


async def test_client_get_raw_rejects_bad_path_without_sending(tmp_path):
    sent = []
    transport = httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200, json={}))

    class Auth:
        async def get_access_token(self):
            return "token"

    settings = Settings(
        _env_file=None,
        oauth_client_id="id",
        oauth_client_secret="secret",
        site_ids="1",
        token_file=str(tmp_path / "t.json"),
        usage_file=str(tmp_path / "u.json"),
    )
    async with SolarEdgeClient(settings, token_manager=Auth(), transport=transport) as client:
        with pytest.raises(ValueError):
            await client.get_raw("https://evil.example/")
        assert await client.get_raw("/sites/1", [("a", "b")]) == {}
    assert len(sent) == 1
    assert str(sent[0].url) == "https://monitoringapi.solaredge.com/v2/sites/1?a=b"
