"""Tests for the global -c/--config option (alternate .env file)."""

import pytest
from click.testing import CliRunner

import seh.api.client as client_module
from seh.cli import cli
from seh.config.settings import get_settings
from tests.test_cli_check_api import FakeClient

ISOLATED_VARS = (
    "SEH_OAUTH_CLIENT_ID",
    "SEH_OAUTH_CLIENT_SECRET",
    "SEH_SITE_IDS",
    "SEH_DATABASE_URL",
    "SEH_LOG_FILE",
    "SEH_LOG_LEVEL",
    "SEH_SKIP_DATA_TYPES",
    "SEH_TOKEN_FILE",
)


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """A working directory whose default .env differs from an alternate config file."""
    for var in ISOLATED_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "SEH_SITE_IDS=1111\nSEH_TOKEN_FILE=default-tokens.json\n", encoding="utf-8"
    )
    other = tmp_path / "other.env"
    other.write_text(
        "SEH_OAUTH_CLIENT_ID=id\nSEH_OAUTH_CLIENT_SECRET=secret\n"
        "SEH_SITE_IDS=4242\nSEH_TOKEN_FILE=other-tokens.json\n"
        "SEH_DATABASE_URL=sqlite:///:memory:\n",
        encoding="utf-8",
    )
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_get_settings_reads_given_file(workdir):
    assert get_settings(str(workdir / "other.env")).require_site_ids() == [4242]
    assert get_settings().require_site_ids() == [1111]


def test_environment_variables_override_the_file(workdir, monkeypatch):
    monkeypatch.setenv("SEH_SITE_IDS", "9999")
    assert get_settings(str(workdir / "other.env")).require_site_ids() == [9999]


def test_cli_config_option_selects_file(workdir):
    result = CliRunner().invoke(cli, ["-c", "other.env", "auth", "status"])
    assert "other-tokens.json" in result.output
    assert "default-tokens.json" not in result.output


def test_cli_without_config_option_uses_dot_env(workdir):
    result = CliRunner().invoke(cli, ["auth", "status"])
    assert "default-tokens.json" in result.output


def test_cli_config_option_requires_existing_file(workdir):
    result = CliRunner().invoke(cli, ["-c", "missing.env", "auth", "status"])
    assert result.exit_code == 2
    assert "does not exist" in result.output


def test_check_api_update_config_writes_selected_file(workdir, monkeypatch):
    monkeypatch.setattr(client_module, "SolarEdgeClient", FakeClient)

    result = CliRunner().invoke(cli, ["-c", "other.env", "check-api", "--update-config"])

    assert result.exit_code == 0, result.output
    assert "SEH_SKIP_DATA_TYPES=alert,optimizer_telemetry" in (workdir / "other.env").read_text(
        encoding="utf-8"
    )
    assert "SEH_SKIP_DATA_TYPES" not in (workdir / ".env").read_text(encoding="utf-8")
