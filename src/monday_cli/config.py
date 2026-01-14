"""Configuration management for Monday CLI."""


from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from monday_cli.constants import (
    DEFAULT_LOG_LEVEL,
    DEFAULT_RATE_LIMIT_CALLS,
    DEFAULT_RATE_LIMIT_PERIOD,
    DEFAULT_RETRY_BACKOFF_FACTOR,
    DEFAULT_RETRY_MAX_ATTEMPTS,
    MONDAY_API_URL,
)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Monday.com API Configuration
    monday_api_token: str = Field(..., description="Monday.com API token")
    monday_api_url: str = Field(default=MONDAY_API_URL, description="Monday.com API URL")

    # Logging Configuration
    log_level: str = Field(default=DEFAULT_LOG_LEVEL, description="Logging level")

    # Retry Configuration
    retry_max_attempts: int = Field(
        default=DEFAULT_RETRY_MAX_ATTEMPTS, description="Maximum retry attempts"
    )
    retry_backoff_factor: float = Field(
        default=DEFAULT_RETRY_BACKOFF_FACTOR, description="Retry backoff multiplier"
    )

    # Rate Limiting Configuration
    rate_limit_calls: int = Field(
        default=DEFAULT_RATE_LIMIT_CALLS, description="Max API calls per period"
    )
    rate_limit_period: int = Field(
        default=DEFAULT_RATE_LIMIT_PERIOD, description="Rate limit period in seconds"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create settings instance.

    Returns:
        Settings instance loaded from environment variables.

    Raises:
        ValidationError: If required settings are missing or invalid.
    """
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings


def reset_settings() -> None:
    """Reset settings instance (useful for testing)."""
    global _settings
    _settings = None
