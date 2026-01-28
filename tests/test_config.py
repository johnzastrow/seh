"""Tests for configuration settings."""

import os

import pytest
from pydantic import ValidationError

from seh.config.settings import Settings


class TestSettings:
    """Test Settings class."""

    def test_settings_with_required_fields(self):
        """Test that settings work with required fields."""
        settings = Settings(
            api_key="test_key",
            database_url="sqlite:///:memory:",
        )
        assert settings.api_key.get_secret_value() == "test_key"
        assert settings.database_url == "sqlite:///:memory:"

    def test_settings_default_values(self, monkeypatch):
        """Test default values are set correctly."""
        # Clear environment variables that might override defaults
        monkeypatch.delenv("SEH_DATABASE_URL", raising=False)
        monkeypatch.delenv("SEH_LOG_LEVEL", raising=False)

        settings = Settings(api_key="test_key")

        assert settings.api_base_url == "https://monitoringapi.solaredge.com"
        assert settings.api_timeout == 10
        assert settings.api_max_concurrent == 3
        assert settings.api_daily_limit == 300
        # database_url may be overridden by .env file, just check it's set
        assert settings.database_url is not None
        assert settings.energy_lookback_days == 365
        assert settings.power_lookback_days == 7
        assert settings.sync_overlap_minutes == 15
        # log_level may be overridden by .env file
        assert settings.log_level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    def test_settings_custom_values(self):
        """Test custom values override defaults."""
        settings = Settings(
            api_key="test_key",
            api_timeout=30,
            api_max_concurrent=5,
            energy_lookback_days=180,
            log_level="DEBUG",
        )

        assert settings.api_timeout == 30
        assert settings.api_max_concurrent == 5
        assert settings.energy_lookback_days == 180
        assert settings.log_level == "DEBUG"

    def test_settings_api_key_is_secret(self):
        """Test that API key is treated as secret."""
        settings = Settings(api_key="secret_key_123")

        # Should not expose key in string representation
        assert "secret_key_123" not in str(settings)
        assert "secret_key_123" not in repr(settings)

        # But should be accessible via get_secret_value
        assert settings.api_key.get_secret_value() == "secret_key_123"

    def test_settings_log_level_validation(self):
        """Test log level validation."""
        # Valid log levels
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            settings = Settings(api_key="test", log_level=level)
            assert settings.log_level == level

    def test_settings_database_url_formats(self):
        """Test various database URL formats."""
        urls = [
            "sqlite:///./test.db",
            "sqlite:///:memory:",
            "postgresql+psycopg://user:pass@localhost:5432/db",
        ]
        for url in urls:
            settings = Settings(api_key="test", database_url=url)
            assert settings.database_url == url


class TestSettingsFromEnv:
    """Test Settings loading from environment variables."""

    def test_settings_from_env_with_prefix(self, monkeypatch):
        """Test settings load from SEH_ prefixed env vars."""
        monkeypatch.setenv("SEH_API_KEY", "env_api_key")
        monkeypatch.setenv("SEH_DATABASE_URL", "sqlite:///env.db")
        monkeypatch.setenv("SEH_LOG_LEVEL", "DEBUG")

        # Clear any cached settings
        from seh.config.settings import get_settings
        get_settings.cache_clear()

        settings = Settings()
        assert settings.api_key.get_secret_value() == "env_api_key"
        assert settings.database_url == "sqlite:///env.db"
        assert settings.log_level == "DEBUG"

    def test_settings_ignores_extra_env_vars(self, monkeypatch):
        """Test that extra env vars don't cause errors."""
        monkeypatch.setenv("SEH_API_KEY", "test_key")
        monkeypatch.setenv("SOME_OTHER_VAR", "value")
        monkeypatch.setenv("DB_HOST", "localhost")  # Common extra var

        # Should not raise
        settings = Settings()
        assert settings.api_key.get_secret_value() == "test_key"
