"""Tests for configuration settings."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from seh.config.settings import Settings
from seh.utils.exceptions import ConfigurationError

AUTH_ENV_VARS = (
    "SEH_API_KEY",
    "SEH_OAUTH_CLIENT_ID",
    "SEH_OAUTH_CLIENT_SECRET",
    "SEH_SITE_IDS",
    "SEH_API_BASE_URL",
    "SEH_TOKEN_FILE",
)


@pytest.fixture
def clean_env(monkeypatch):
    """Isolate tests from the developer's environment variables."""
    for var in (*AUTH_ENV_VARS, "SEH_DATABASE_URL", "SEH_LOG_LEVEL"):
        monkeypatch.delenv(var, raising=False)


def make_settings(**kwargs) -> Settings:
    """Settings that ignore the repository's .env file."""
    return Settings(_env_file=None, **kwargs)


class TestSettings:
    """Test Settings class."""

    def test_settings_need_no_credentials_to_construct(self, clean_env):
        """Non-API commands (init-db, export) must work without OAuth credentials."""
        settings = make_settings(database_url="sqlite:///:memory:")
        assert settings.database_url == "sqlite:///:memory:"
        assert settings.oauth_client_id is None

    def test_settings_default_values(self, clean_env):
        """Test default values are set correctly."""
        settings = make_settings()

        assert settings.api_base_url == "https://monitoringapi.solaredge.com/v2"
        assert settings.oauth_authorize_url == "https://connect.solaredge.com/authorize"
        assert settings.oauth_token_url == "https://monitoringapi.solaredge.com/v2/oauth2/token"
        assert settings.api_timeout == 10
        assert settings.api_max_concurrent == 3
        assert settings.api_monthly_credits == 2000
        assert settings.api_per_minute_limit == 10
        assert settings.oauth_redirect_uri == "http://127.0.0.1:8765/callback"
        assert settings.database_url == "sqlite:///./seh.db"
        assert settings.energy_lookback_days == 365
        assert settings.power_lookback_days == 7
        assert settings.sync_overlap_minutes == 15
        assert settings.log_level == "INFO"

    def test_settings_custom_values(self, clean_env):
        """Test custom values override defaults."""
        settings = make_settings(
            api_timeout=30,
            api_max_concurrent=5,
            energy_lookback_days=180,
            log_level="DEBUG",
            oauth_redirect_port=9000,
        )

        assert settings.api_timeout == 30
        assert settings.api_max_concurrent == 5
        assert settings.energy_lookback_days == 180
        assert settings.log_level == "DEBUG"
        assert settings.oauth_redirect_uri == "http://127.0.0.1:9000/callback"

    def test_client_secret_is_secret(self, clean_env):
        """The OAuth client secret must not appear in string representations."""
        settings = make_settings(oauth_client_id="id", oauth_client_secret="secret_value_123")

        assert "secret_value_123" not in str(settings)
        assert "secret_value_123" not in repr(settings)
        assert settings.oauth_client_secret.get_secret_value() == "secret_value_123"

    @pytest.mark.parametrize(
        "field", ["api_base_url", "oauth_authorize_url", "oauth_token_url", "oauth_revoke_url"]
    )
    def test_plain_http_urls_are_rejected(self, clean_env, field):
        """Tokens and secrets must never be sent over plain HTTP."""
        with pytest.raises(ValidationError, match="https"):
            make_settings(**{field: "http://example.com/v2"})

    def test_trailing_slash_is_stripped_from_urls(self, clean_env):
        settings = make_settings(api_base_url="https://example.com/v2/")
        assert settings.api_base_url == "https://example.com/v2"

    @pytest.mark.parametrize("port", [80, 70000])
    def test_redirect_port_out_of_range_is_rejected(self, clean_env, port):
        with pytest.raises(ValidationError):
            make_settings(oauth_redirect_port=port)

    def test_token_path_expands_home(self, clean_env):
        settings = make_settings(token_file="~/seh-tokens.json")
        assert settings.token_path == Path.home() / "seh-tokens.json"

    def test_settings_log_level_validation(self, clean_env):
        """Test log level validation."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            settings = make_settings(log_level=level)
            assert settings.log_level == level

    def test_settings_database_url_formats(self, clean_env):
        """Test various database URL formats."""
        urls = [
            "sqlite:///./test.db",
            "sqlite:///:memory:",
            "postgresql+psycopg://user:pass@localhost:5432/db",
        ]
        for url in urls:
            settings = make_settings(database_url=url)
            assert settings.database_url == url


class TestRequireOAuthCredentials:
    """Credential checks performed when an API command actually runs."""

    def test_returns_credentials_when_set(self, clean_env):
        settings = make_settings(oauth_client_id=" id ", oauth_client_secret="secret")
        assert settings.require_oauth_credentials() == ("id", "secret")

    def test_missing_credentials_raise(self, clean_env):
        with pytest.raises(ConfigurationError, match="SEH_OAUTH_CLIENT_ID"):
            make_settings().require_oauth_credentials()

    def test_missing_secret_raises(self, clean_env):
        with pytest.raises(ConfigurationError):
            make_settings(oauth_client_id="id").require_oauth_credentials()

    def test_legacy_v1_key_alone_gives_migration_message(self, clean_env):
        settings = make_settings(api_key="old-v1-key")
        with pytest.raises(ConfigurationError, match="V1 key"):
            settings.require_oauth_credentials()


class TestRequireSiteIds:
    def test_returns_parsed_ids(self, clean_env):
        assert make_settings(site_ids="123, 456").require_site_ids() == [123, 456]

    def test_missing_site_ids_raise(self, clean_env):
        with pytest.raises(ConfigurationError, match="SEH_SITE_IDS must be set"):
            make_settings().require_site_ids()

    def test_malformed_site_ids_raise(self, clean_env):
        with pytest.raises(ConfigurationError, match="numeric"):
            make_settings(site_ids="123,abc").require_site_ids()


class TestSettingsFromEnv:
    """Test Settings loading from environment variables."""

    def test_settings_from_env_with_prefix(self, clean_env, monkeypatch):
        """Test settings load from SEH_ prefixed env vars."""
        monkeypatch.setenv("SEH_OAUTH_CLIENT_ID", "env_client")
        monkeypatch.setenv("SEH_OAUTH_CLIENT_SECRET", "env_secret")
        monkeypatch.setenv("SEH_SITE_IDS", "4242")
        monkeypatch.setenv("SEH_DATABASE_URL", "sqlite:///env.db")
        monkeypatch.setenv("SEH_LOG_LEVEL", "DEBUG")

        from seh.config.settings import get_settings

        get_settings.cache_clear()

        settings = make_settings()
        assert settings.require_oauth_credentials() == ("env_client", "env_secret")
        assert settings.require_site_ids() == [4242]
        assert settings.database_url == "sqlite:///env.db"
        assert settings.log_level == "DEBUG"

    def test_settings_ignores_extra_env_vars(self, clean_env, monkeypatch):
        """Test that extra env vars don't cause errors."""
        monkeypatch.setenv("SOME_OTHER_VAR", "value")
        monkeypatch.setenv("DB_HOST", "localhost")

        settings = make_settings()
        assert settings.oauth_client_id is None


class TestPowerTimeUnit:
    def test_default_is_v2_quarter_hour(self, clean_env):
        assert make_settings().power_time_unit == "QUARTER_HOUR"

    def test_v1_name_is_accepted(self, clean_env):
        assert make_settings(power_time_unit="QUARTER_OF_AN_HOUR").power_time_unit == "QUARTER_HOUR"

    def test_unknown_unit_is_rejected(self, clean_env):
        with pytest.raises(ValidationError):
            make_settings(power_time_unit="FIVE_MINUTES")
