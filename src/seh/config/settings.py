"""Application settings using Pydantic Settings."""

import re
from functools import lru_cache
from pathlib import Path
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

    # Site Filtering
    site_ids: str | None = Field(
        default=None,
        description="Comma-separated list of site IDs to sync (syncs all if not set)",
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
    power_time_unit: Literal["QUARTER_OF_AN_HOUR", "HOUR", "DAY", "WEEK", "MONTH", "YEAR"] = Field(
        default="QUARTER_OF_AN_HOUR",
        description="Time unit for power data (QUARTER_OF_AN_HOUR is 15-min intervals)",
    )

    # Error Handling Configuration
    error_handling: Literal["strict", "lenient", "skip"] = Field(
        default="lenient",
        description="Error handling mode: strict (fail on first error), lenient (log and continue), skip (silent skip)",
    )
    max_retries: int = Field(
        default=3,
        description="Maximum number of retries for failed API requests",
    )
    retry_delay: float = Field(
        default=2.0,
        description="Base delay in seconds between retries (uses exponential backoff)",
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

    # Email Notification Configuration
    smtp_enabled: bool = Field(
        default=False,
        description="Enable email notifications",
    )
    smtp_host: str = Field(
        default="smtp.gmail.com",
        description="SMTP server hostname",
    )
    smtp_port: int = Field(
        default=587,
        description="SMTP server port (587 for TLS, 465 for SSL)",
    )
    smtp_username: str | None = Field(
        default=None,
        description="SMTP authentication username",
    )
    smtp_password: SecretStr | None = Field(
        default=None,
        description="SMTP authentication password",
    )
    smtp_use_tls: bool = Field(
        default=True,
        description="Use TLS for SMTP connection",
    )
    smtp_from_email: str | None = Field(
        default=None,
        description="From email address for notifications",
    )
    smtp_to_emails: str | None = Field(
        default=None,
        description="Comma-separated list of recipient email addresses",
    )
    notify_on_error: bool = Field(
        default=True,
        description="Send email notification on sync errors",
    )
    notify_on_success: bool = Field(
        default=False,
        description="Send email notification on successful sync",
    )

    # Data Type Filtering
    skip_data_types: str | None = Field(
        default=None,
        description="Comma-separated data types to skip during sync (e.g., 'meter,alert')",
    )

    # Valid data types for skip_data_types
    VALID_DATA_TYPES: frozenset[str] = frozenset({
        "site", "equipment", "energy", "power", "storage", "meter",
        "environmental", "alert", "inventory", "inverter_telemetry", "optimizer_telemetry"
    })

    def get_site_ids_list(self) -> list[int] | None:
        """Parse site_ids setting into a list of integers."""
        if not self.site_ids:
            return None
        try:
            return [int(s.strip()) for s in self.site_ids.split(",") if s.strip()]
        except ValueError:
            return None

    def get_to_email_list(self) -> list[str]:
        """Parse smtp_to_emails into a list of email addresses."""
        if not self.smtp_to_emails:
            return []
        return [e.strip() for e in self.smtp_to_emails.split(",") if e.strip()]

    def get_skip_data_types_list(self) -> list[str] | None:
        """Parse skip_data_types into a list of data type strings.

        Returns:
            List of valid data type strings to skip, or None if not set.
        """
        if not self.skip_data_types:
            return None
        types = [t.strip().lower() for t in self.skip_data_types.split(",") if t.strip()]
        # Filter to only valid data types
        valid_types = [t for t in types if t in self.VALID_DATA_TYPES]
        return valid_types if valid_types else None


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()


def update_env_file(key: str, value: str, env_path: str = ".env") -> bool:
    """Update or add a key in .env file, preserving comments and formatting.

    Args:
        key: Environment variable name (e.g., 'SEH_SKIP_DATA_TYPES').
        value: Value to set.
        env_path: Path to .env file.

    Returns:
        True if file was updated, False if file doesn't exist.
    """
    path = Path(env_path)

    # Read existing content or start fresh
    if path.exists():
        content = path.read_text()
    else:
        content = ""

    # Pattern to match the key (with optional leading comment/whitespace)
    pattern = re.compile(rf'^(#?\s*)?{re.escape(key)}\s*=.*$', re.MULTILINE)

    # Check if key already exists
    match = pattern.search(content)
    if match:
        # Replace existing line (uncomment if commented)
        new_content = pattern.sub(f'{key}={value}', content)
    else:
        # Append to end of file
        if content and not content.endswith('\n'):
            content += '\n'
        new_content = content + f'{key}={value}\n'

    path.write_text(new_content)
    return True
