"""Application configuration loaded from environment variables and env files.

Precedence (highest wins):

1. Real OS environment variables (e.g. injected by Docker/k8s/CI).
2. ``config/<APP_ENV>.env`` — environment specific, committed, no secrets.
3. ``.env`` — local developer file, never committed.
4. Field defaults declared in :class:`Settings`.

Secrets (``LLM_API_KEY``) are typed as :class:`pydantic.SecretStr` so they are
never accidentally rendered by ``repr()`` or dumped into logs.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["json", "text"]
AppEnv = Literal["dev", "test", "prod"]
ProviderName = Literal["mock", "openai"]
MockFailMode = Literal["none", "timeout", "error", "empty"]


class Settings(BaseSettings):
    """Typed, validated application settings."""

    model_config = SettingsConfigDict(
        env_file=None,  # resolved explicitly in :func:`get_settings`
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ------------------------------------------------------
    app_env: AppEnv = "dev"
    app_name: str = "docqa-service"
    app_version: str = "1.0.0"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_log_level: LogLevel = "INFO"
    app_log_format: LogFormat = "json"
    app_max_request_bytes: int = Field(default=262_144, ge=1024)
    request_id_header: str = "X-Request-ID"

    # --- LLM --------------------------------------------------------------
    llm_provider: ProviderName = "mock"
    llm_api_key: Optional[SecretStr] = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = Field(default=20.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    llm_retry_backoff_seconds: float = Field(default=0.5, ge=0)
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=400, ge=16, le=8192)

    # --- Mock provider (local demo & CI, no network) -----------------------
    mock_latency_ms: int = Field(default=0, ge=0, le=60_000)
    mock_fail_mode: MockFailMode = "none"

    # --- Cache ------------------------------------------------------------
    cache_enabled: bool = True
    cache_ttl_seconds: int = Field(default=300, ge=1, le=86_400)
    cache_max_entries: int = Field(default=1000, ge=1, le=1_000_000)

    # --- Business rules / limits ------------------------------------------
    fallback_enabled: bool = True
    min_question_chars: int = Field(default=3, ge=1)
    max_question_chars: int = Field(default=500, ge=10)
    max_context_chars: int = Field(default=20_000, ge=100)
    top_k_excerpts: int = Field(default=4, ge=1, le=20)
    max_excerpt_chars: int = Field(default=1200, ge=100)
    max_answer_chars: int = Field(default=2000, ge=50)

    @field_validator("app_log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("llm_base_url")
    @classmethod
    def _strip_base_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("LLM_BASE_URL must not be empty")
        return value.rstrip("/")

    @field_validator("request_id_header")
    @classmethod
    def _non_empty_header(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("REQUEST_ID_HEADER must not be empty")
        return value.strip()

    @model_validator(mode="after")
    def _validate_business_rules(self) -> Settings:
        if self.max_question_chars <= self.min_question_chars:
            raise ValueError("MAX_QUESTION_CHARS must be greater than MIN_QUESTION_CHARS")
        if self.max_excerpt_chars > self.max_context_chars:
            raise ValueError("MAX_EXCERPT_CHARS must not exceed MAX_CONTEXT_CHARS")

        api_key = self.llm_api_key.get_secret_value().strip() if self.llm_api_key else ""
        if self.llm_provider == "openai" and not api_key:
            raise ValueError("LLM_API_KEY is required when LLM_PROVIDER=openai")
        if self.app_env == "prod" and self.llm_provider == "mock":
            raise ValueError("LLM_PROVIDER=mock is not allowed when APP_ENV=prod")
        return self

    @property
    def api_key(self) -> Optional[str]:
        """Plain-text API key accessor (only call where the key is required)."""
        if self.llm_api_key is None:
            return None
        value = self.llm_api_key.get_secret_value().strip()
        return value or None

    def safe_dict(self) -> dict:
        """Settings representation with secrets masked (safe for logs)."""
        data = self.model_dump()
        if data.get("llm_api_key"):
            data["llm_api_key"] = "***"
        return data


def env_files_for(app_env: Optional[str] = None) -> Tuple[Path, ...]:
    """Return env files in increasing priority order for the given environment."""
    files: List[Path] = [PROJECT_ROOT / ".env"]
    env_name = (app_env or os.environ.get("APP_ENV") or "dev").strip().lower()
    specific = PROJECT_ROOT / "config" / f"{env_name}.env"
    if specific.is_file():
        files.append(specific)
    return tuple(files)


def load_settings(app_env: Optional[str] = None) -> Settings:
    """Build settings from defaults, env files and the OS environment."""
    return Settings(_env_file=env_files_for(app_env))  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor used by the application and the CLI."""
    return load_settings()


def reload_settings() -> Settings:
    """Clear the cache and reload settings (useful in tests and tooling)."""
    get_settings.cache_clear()
    return get_settings()
