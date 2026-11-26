from __future__ import annotations

from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from conftest import SAMPLE_CONTEXT, SAMPLE_QUESTION, StubLLMClient, make_payload
from docqa.core.errors import LLMTimeoutError, LLMUnavailableError

API = "/api/v1/qa"


def test_health_reports_service_state(api_client: TestClient) -> None:
    api_client.post(API, json=make_payload())
    response = api_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provider"] == "mock"
    assert body["cache"]["ttl_seconds"] == 60
    assert body["counters"]["requests_total"] == 1


def test_ready_probe(api_client: TestClient) -> None:
    response = api_client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_root_lists_endpoints(api_client: TestClient) -> None:
    response = api_client.get("/")
    assert response.status_code == 200
    assert response.json()["endpoint"] == "POST /api/v1/qa"


def test_successful_question(api_client: TestClient, stub_client: StubLLMClient) -> None:
    response = api_client.post(API, json=make_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == stub_client.text
    assert body["degraded"] is False
    assert body["cached"] is False
    assert body["provider"] == "stub"
    assert body["citations"]
    assert body["usage"]["prompt_tokens"] == 11
    assert response.headers["X-Cache"] == "MISS"
    assert response.headers["X-Request-ID"]
    assert stub_client.calls == 1


def test_request_id_is_propagated(api_client: TestClient) -> None:
    response = api_client.post(API, json=make_payload(), headers={"X-Request-ID": "req-42"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-42"
    assert response.json()["request_id"] == "req-42"


def test_repeat_request_is_served_from_cache(
    api_client: TestClient, stub_client: StubLLMClient
) -> None:
    first = api_client.post(API, json=make_payload())
    second = api_client.post(API, json=make_payload())

    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert second.json()["cached"] is True
    assert second.json()["answer"] == first.json()["answer"]
    assert stub_client.calls == 1


def test_cache_can_be_disabled(make_app: Callable[..., Any], stub_client: StubLLMClient) -> None:
    app = make_app(stub_client, cache_enabled=False)
    with TestClient(app) as client:
        client.post(API, json=make_payload())
        second = client.post(API, json=make_payload())
    assert second.headers["X-Cache"] == "MISS"
    assert stub_client.calls == 2


def test_cache_key_depends_on_question(api_client: TestClient, stub_client: StubLLMClient) -> None:
    api_client.post(API, json=make_payload())
    api_client.post(API, json=make_payload(question="А какие лимиты у документа?"))
    assert stub_client.calls == 2


@pytest.mark.parametrize(
    "payload",
    [
        make_payload(question=""),
        make_payload(question="   "),
        make_payload(question="да"),
        make_payload(question="а" * 600),
        make_payload(context="   "),
        make_payload(context="а" * 25_000),
        {"question": SAMPLE_QUESTION},
        {"context": SAMPLE_CONTEXT},
        {**make_payload(), "unexpected_field": 1},
    ],
)
def test_invalid_payloads_return_422(api_client: TestClient, payload: dict) -> None:
    response = api_client.post(API, json=payload)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["request_id"]


def test_too_large_request_returns_413(make_app: Callable[..., Any]) -> None:
    app = make_app(app_max_request_bytes=1024)
    with TestClient(app) as client:
        response = client.post(API, json=make_payload(context="а" * 2000))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_llm_outage_returns_extractive_fallback(make_app: Callable[..., Any]) -> None:
    failing = StubLLMClient(error=LLMUnavailableError("provider is down"))
    app = make_app(failing)
    with TestClient(app) as client:
        response = client.post(API, json=make_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is True
    assert body["degradation_reason"] == "llm_unavailable"
    assert body["provider"] == "extractive"
    assert body["answer"]
    assert "таймаут" in body["answer"].lower()
    assert response.headers["X-Degraded"] == "true"
    assert response.headers["X-Degradation-Reason"] == "llm_unavailable"


def test_llm_timeout_is_degraded(make_app: Callable[..., Any]) -> None:
    failing = StubLLMClient(error=LLMTimeoutError("timed out"))
    app = make_app(failing)
    with TestClient(app) as client:
        response = client.post(API, json=make_payload())
    assert response.status_code == 200
    assert response.json()["degradation_reason"] == "llm_timeout"


def test_fallback_can_be_disabled(make_app: Callable[..., Any]) -> None:
    failing = StubLLMClient(error=LLMUnavailableError("provider is down"))
    app = make_app(failing)
    with TestClient(app) as client:
        response = client.post(API, json=make_payload(allow_fallback=False))

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "llm_unavailable"
    assert "X-Degraded" not in response.headers


def test_empty_model_answer_uses_fallback(make_app: Callable[..., Any]) -> None:
    empty = StubLLMClient(text="   ")
    app = make_app(empty)
    with TestClient(app) as client:
        response = client.post(API, json=make_payload())
    assert response.status_code == 200
    assert response.json()["degraded"] is True
    assert response.json()["degradation_reason"] == "postprocessing_error"


def test_top_k_limits_citations(api_client: TestClient) -> None:
    response = api_client.post(API, json=make_payload(top_k=2))
    assert response.status_code == 200
    assert len(response.json()["citations"]) <= 2


def test_health_does_not_leak_api_key() -> None:
    from docqa.core.config import Settings

    settings = Settings(
        llm_provider="openai", llm_api_key="sk-hidden-value", app_env="test", _env_file=None
    )
    assert "sk-hidden-value" not in str(settings.safe_dict())
