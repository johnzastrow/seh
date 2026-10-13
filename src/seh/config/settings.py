"""Application settings using Pydantic Settings."""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from seh.utils.exceptions import ConfigurationError

# Loopback host for the OAuth redirect; fixed so the listener is never exposed on the network.
OAUTH_REDIRECT_HOST = "127.0.0.1"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="SEH_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra environment variables
    )

    # API Configuration (SolarEdge Monitoring API V2)
    api_base_url: str = Field(
        default="https://monitoringapi.solaredge.com/v2",
        description="SolarEdge Monitoring API V2 base URL",
    )
    api_timeout: int = Field(default=10, description="API request timeout in seconds")
    api_max_concurrent: int = Field(default=3, description="Maximum concurrent API requests")
    api_monthly_credits: int = Field(
        default=2000,
        ge=1,
        description="Monthly API credit budget (1 credit per call; Free tier is 2000)",
    )
    api_per_minute_limit: int = Field(
        default=10,
        ge=1,
        description="Maximum API calls per minute (Free tier is 10)",
    )

    # Legacy V1 key: no longer accepted by SolarEdge; kept only to give a clear error.
    api_key: SecretStr | None = Field(
        default=None,
        description="Deprecated V1 API key (retired 2026-11-01); use OAuth settings instead",
    )

    # OAuth2 Site Access (developer.solaredge.com application)
    oauth_client_id: str | None = Field(
        default=None,
        description="OAuth client ID of the SolarEdge developer application",
    )
    oauth_client_secret: SecretStr | None = Field(
        default=None,
        description="OAuth client secret of the SolarEdge developer application",
    )
    oauth_authorize_url: str = Field(
        default="https://connect.solaredge.com/authorize",
        description="OAuth authorization endpoint",
    )
    oauth_token_url: str = Field(
        default="https://monitoringapi.solaredge.com/v2/oauth2/token",
        description="OAuth token endpoint",
    )
    oauth_revoke_url: str = Field(
        default="https://monitoringapi.solaredge.com/v2/oauth2/revoke-token",
        description="OAuth token revocation endpoint",
    )
    oauth_redirect_port: int = Field(
        default=8765,
        ge=1024,
        le=65535,
        description="Loopback port for the OAuth redirect (must match the registered redirect URI)",
    )
    usage_file: str = Field(
        default="~/.config/seh/usage.json",
        min_length=1,
        description="Path of the monthly API credit ledger shared by all seh processes",
    )
    token_file: str = Field(
        default="~/.config/seh/tokens.json",
        min_length=1,
        description="Path of the OAuth token file (written with owner-only permissions)",
    )

    # Database Configuration
    database_url: str = Field(
        default="sqlite:///./seh.db",
        description="Database connection URL",
    )

    # Site Filtering
    site_ids: str | None = Field(
        default=None,
        description="Comma-separated site IDs to sync (required: API V2 cannot list sites)",
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
    power_details_lookback_days: int = Field(
        default=25,
        description="Days to look back for the power breakdown (seh_power_details) on first sync",
    )
    sync_overlap_minutes: int = Field(
        default=15,
        description="Overlap buffer in minutes for incremental syncs",
    )
    power_time_unit: Literal["QUARTER_HOUR", "HOUR", "DAY", "WEEK", "MONTH", "YEAR"] = Field(
        default="QUARTER_HOUR",
        description="V2 resolution for power data (QUARTER_HOUR is 15-min intervals)",
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
    VALID_DATA_TYPES: frozenset[str] = frozenset(
        {
            "site",
            "equipment",
            "energy",
            "power",
            "power_details",
            "storage",
            "meter",
            "environmental",
            "alert",
            "inventory",
            "inverter_telemetry",
            "optimizer_telemetry",
        }
    )

    @field_validator("power_time_unit", mode="before")
    @classmethod
    def _v1_time_unit_alias(cls, value: object) -> object:
        """Accept the V1 name so existing .env files keep working."""
        return "QUARTER_HOUR" if value == "QUARTER_OF_AN_HOUR" else value

    @field_validator("api_base_url", "oauth_authorize_url", "oauth_token_url", "oauth_revoke_url")
    @classmethod
    def _require_https(cls, value: str) -> str:
        """Tokens and client secrets must never travel over plain HTTP."""
        if not value.lower().startswith("https://"):
            raise ValueError("must be an https:// URL")
        return value.rstrip("/")

    @property
    def oauth_redirect_uri(self) -> str:
        """Redirect URI registered with the SolarEdge developer application."""
        return f"http://{OAUTH_REDIRECT_HOST}:{self.oauth_redirect_port}/callback"

    @property
    def usage_path(self) -> Path:
        """Credit ledger path with ~ expanded."""
        return Path(self.usage_file).expanduser()

    @property
    def token_path(self) -> Path:
        """Token file path with ~ expanded."""
        return Path(self.token_file).expanduser()

    def require_oauth_credentials(self) -> tuple[str, str]:
        """Return (client_id, client_secret) or raise a ConfigurationError explaining the fix."""
        client_id = (self.oauth_client_id or "").strip()
        secret = (
            self.oauth_client_secret.get_secret_value().strip() if self.oauth_client_secret else ""
        )
        if client_id and secret:
            return client_id, secret
        if self.api_key is not None:
            raise ConfigurationError(
                "SEH_API_KEY is a SolarEdge V1 key, which no longer works. Create an app at "
                "https://developer.solaredge.com/, set SEH_OAUTH_CLIENT_ID and "
                "SEH_OAUTH_CLIENT_SECRET, then run 'seh auth login'."
            )
        raise ConfigurationError(
            "SEH_OAUTH_CLIENT_ID and SEH_OAUTH_CLIENT_SECRET must be set "
            "(from your app at https://developer.solaredge.com/)."
        )

    def require_site_ids(self) -> list[int]:
        """Return configured site IDs; V2 OAuth tokens cannot list sites, so they are required."""
        ids = self.get_site_ids_list()
        if self.site_ids and not ids:
            raise ConfigurationError(
                "SEH_SITE_IDS must be a comma-separated list of numeric site IDs."
            )
        if not ids:
            raise ConfigurationError(
                "SEH_SITE_IDS must be set: SolarEdge V2 does not let OAuth apps list sites."
            )
        return ids

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


DEFAULT_ENV_FILE = ".env"


@lru_cache
def get_settings(env_file: str | None = None) -> Settings:
    """Get cached application settings.

    Args:
        env_file: .env file to read (default: ".env" in the current directory).
            Environment variables still take precedence over values in the file.
    """
    # _env_file is a pydantic-settings init option that mypy cannot see without the plugin.
    return Settings(_env_file=env_file or DEFAULT_ENV_FILE)  # type: ignore[call-arg]


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
    pattern = re.compile(rf"^(#?\s*)?{re.escape(key)}\s*=.*$", re.MULTILINE)

    # Check if key already exists
    match = pattern.search(content)
    if match:
        # Replace existing line (uncomment if commented)
        new_content = pattern.sub(f"{key}={value}", content)
    else:
        # Append to end of file
        if content and not content.endswith("\n"):
            content += "\n"
        new_content = content + f"{key}={value}\n"

    path.write_text(new_content)
    return True
