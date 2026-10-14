"""
Application configuration loaded from environment variables.

Uses pydantic-settings for validated, typed configuration.
All secrets are loaded server-side only.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings. Values come from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_env: str = Field(default="development", description="development | staging | production")
    app_debug: bool = Field(default=False)
    app_log_level: str = Field(default="info")

    # --- Server ---
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)

    # --- CORS ---
    cors_origins: str = Field(
        default="http://localhost:3000",
        description="Comma-separated allowed origins",
    )

    # --- Request limits ---
    max_prompt_length: int = Field(default=32_000)
    request_timeout_seconds: int = Field(default=120)

    # --- Provider API keys (server-side only) ---
    openai_api_key: Optional[str] = Field(default=None)
    anthropic_api_key: Optional[str] = Field(default=None)
    google_api_key: Optional[str] = Field(default=None)

    # --- Ollama ---
    ollama_base_url: str = Field(default="http://localhost:11434")

    # --- Jev (experimental) ---
    jev_api_key: Optional[str] = Field(default=None)
    jev_base_url: Optional[str] = Field(default=None)

    # --- Database (future) ---
    database_url: Optional[str] = Field(default=None)

    # --- Redis (future) ---
    redis_url: Optional[str] = Field(default=None)

    @field_validator("app_log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"debug", "info", "warning", "error", "critical"}
        if v.lower() not in allowed:
            raise ValueError(f"app_log_level must be one of {allowed}")
        return v.lower()

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    def has_provider_key(self, provider: str) -> bool:
        """Check if a provider API key is configured (non-empty)."""
        key_map = {
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "google": self.google_api_key,
        }
        value = key_map.get(provider)
        return bool(value and value.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings instance. Cached after first load."""
    return Settings()
