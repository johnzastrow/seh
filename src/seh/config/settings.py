"""Application settings using Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="SEH_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra environment variables
    )

    # API Configuration
    api_key: SecretStr = Field(description="SolarEdge API key")
    api_base_url: str = Field(
        default="https://monitoringapi.solaredge.com",
        description="SolarEdge API base URL",
    )
    api_timeout: int = Field(default=10, description="API request timeout in seconds")
    api_max_concurrent: int = Field(default=3, description="Maximum concurrent API requests")
    api_daily_limit: int = Field(default=300, description="Maximum API requests per day")

    # Database Configuration
    database_url: str = Field(
        default="sqlite:///./seh.db",
        description="Database connection URL",
    )

    # Sync Configuration
    energy_lookback_days: int = Field(
        default=365,
        description="Days to look back for energy data on first sync",
    )
    power_lookback_days: int = Field(
        default=7,
        description="Days to look back for power data on first sync",
    )
    sync_overlap_minutes: int = Field(
        default=15,
        description="Overlap buffer in minutes for incremental syncs",
    )

    # Logging Configuration
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level",
    )
    log_file: str | None = Field(
        default=None,
        description="Log file path (logs to console if not set)",
    )
    log_max_bytes: int = Field(
        default=10 * 1024 * 1024,  # 10 MB
        description="Maximum log file size before rotation",
    )
    log_backup_count: int = Field(
        default=5,
        description="Number of backup log files to keep",
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
