"""Tests for 'seh check-api' against the V2 client."""

import pytest
from click.testing import CliRunner

import seh.api.client as client_module
from seh.cli import cli
from seh.utils.exceptions import APIError

DEVICES = [
    {"type": "INVERTER", "serialNumber": "INV-1"},
    {"type": "METER", "serialNumber": "MTR-1"},
]


class FakeClient:
    """Stands in for SolarEdgeClient; alerts are forbidden to exercise the failure path."""

    def __init__(self, settings):
        self.settings = settings

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get_sites(self):
        return [{"siteId": 4242, "name": "Home", "activationStatus": "ACTIVE", "peakPower": 12.76}]

    async def get_site(self, site_id):
        return {"siteId": site_id}

    async def get_devices(self, site_id):
        return DEVICES

    async def get_energy(self, *args, **kwargs):
        return []

    async def get_power(self, *args, **kwargs):
        return []

    async def get_meters_telemetry(self, *args, **kwargs):
        return {}

    async def get_inverters_telemetry(self, *args, **kwargs):
        return {"INV-1": {}}

    async def get_environmental_benefits(self, site_id):
        return {}

    async def get_alerts(self, site_id):
        raise APIError("Authorization Failed", status_code=403)


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEH_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("SEH_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("SEH_SITE_IDS", "4242")
    monkeypatch.setenv("SEH_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.delenv("SEH_LOG_FILE", raising=False)
    monkeypatch.delenv("SEH_SKIP_DATA_TYPES", raising=False)
    monkeypatch.setattr(client_module, "SolarEdgeClient", FakeClient)
    return tmp_path


def test_check_api_lists_sites_and_probes_v2_endpoints(cli_env):
    result = CliRunner().invoke(cli, ["check-api"], input="n\n")

    assert result.exit_code == 0, result.output
    assert "4242" in result.output
    assert "Home" in result.output
    assert "1 inverter(s)" in result.output
    assert "1 meter(s)" in result.output
    assert "No batteries" in result.output
    assert "alert" in result.output and "403" in result.output
    assert "Not available in API V2" in result.output


def test_check_api_update_config_writes_skip_list(cli_env):
    result = CliRunner().invoke(cli, ["check-api", "--update-config"])

    assert result.exit_code == 0, result.output
    env = (cli_env / ".env").read_text(encoding="utf-8")
    assert "SEH_SKIP_DATA_TYPES=alert,optimizer_telemetry" in env
