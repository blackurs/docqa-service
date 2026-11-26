from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from docqa.core.config import Settings, env_files_for, load_settings
from docqa.llm.factory import build_llm_client
from docqa.llm.providers.mock import MockLLMClient
from docqa.llm.providers.openai_compat import OpenAIChatClient


def test_defaults_are_local_and_safe() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_env == "dev"
    assert settings.llm_provider == "mock"
    assert settings.cache_enabled is True
    assert settings.fallback_enabled is True


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "custom-model")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "42")
    monkeypatch.setenv("APP_LOG_LEVEL", "debug")

    settings = Settings(_env_file=None)
    assert settings.llm_model == "custom-model"
    assert settings.cache_ttl_seconds == 42
    assert settings.app_log_level == "DEBUG"


def test_env_file_precedence_last_file_wins(tmp_path: Path) -> None:
    first = tmp_path / "base.env"
    second = tmp_path / "prod.env"
    first.write_text("CACHE_TTL_SECONDS=10\nLLM_MODEL=base-model\n", encoding="utf-8")
    second.write_text("CACHE_TTL_SECONDS=20\n", encoding="utf-8")

    settings = Settings(_env_file=(str(first), str(second)))
    assert settings.cache_ttl_seconds == 20
    assert settings.llm_model == "base-model"


def test_env_files_for_selected_environment() -> None:
    assert env_files_for("dev")[-1].name == "dev.env"
    assert env_files_for("prod")[-1].name == "prod.env"
    assert all(path.name != "test.env" for path in env_files_for("test"))


def test_prod_forbids_mock_provider() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="prod", llm_provider="mock", _env_file=None)


def test_openai_provider_requires_api_key() -> None:
    with pytest.raises(ValidationError):
        Settings(llm_provider="openai", _env_file=None)


def test_api_key_is_masked_in_repr_and_dumps() -> None:
    settings = Settings(llm_provider="openai", llm_api_key="sk-super-secret", _env_file=None)
    assert settings.api_key == "sk-super-secret"
    assert "sk-super-secret" not in repr(settings)
    assert settings.safe_dict()["llm_api_key"] == "***"
    assert all("sk-super-secret" not in str(value) for value in settings.safe_dict().values())


def test_invalid_business_limits_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(min_question_chars=10, max_question_chars=10, _env_file=None)
    with pytest.raises(ValidationError):
        Settings(max_excerpt_chars=5000, max_context_chars=1000, _env_file=None)


def test_factory_returns_mock_by_default() -> None:
    assert isinstance(build_llm_client(Settings(_env_file=None)), MockLLMClient)


def test_factory_builds_openai_client_with_key() -> None:
    settings = Settings(llm_provider="openai", llm_api_key="key", _env_file=None)
    client = build_llm_client(settings)
    assert isinstance(client, OpenAIChatClient)


def test_load_settings_uses_environment_files() -> None:
    settings = load_settings("dev")
    assert settings.app_env in {"dev", "test", "prod"}
