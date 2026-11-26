#!/usr/bin/env python
"""End-to-end demo of docqa-service.

Starts the real HTTP server twice (healthy and simulated outage) and walks
through the scenarios required by the assignment:

1. valid request -> successful answer;
2. repeated request -> cache hit (X-Cache: HIT) and lower latency;
3. invalid request -> HTTP 422 validation error;
4. LLM outage -> HTTP 200 with an extractive fallback (degraded=true).

Run from the repository root:

    .venv/bin/python scripts/demo.py        # Linux/macOS
    .venv\\Scripts\\python.exe scripts\\demo.py   # Windows
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
API_PATH = "/api/v1/qa"
HEALTHY_PORT = 8010
FAULTY_PORT = 8011

QUESTION = "Сколько секунд таймаут по умолчанию и сколько повторных попыток?"
CONTEXT = (ROOT / "data" / "sample_document.txt").read_text(encoding="utf-8")
PAYLOAD: Dict[str, Any] = {"question": QUESTION, "context": CONTEXT, "top_k": 3}


def banner(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def start_server(port: int, extra_env: Dict[str, str]) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "test",
            "LLM_PROVIDER": "mock",
            "MOCK_LATENCY_MS": "40",
            "APP_LOG_LEVEL": "WARNING",
            "CACHE_TTL_SECONDS": "300",
        }
    )
    env.update(extra_env)
    process = subprocess.Popen(
        [
            PYTHON,
            "-m",
            "uvicorn",
            "docqa.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server on port {port} exited early")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                return process
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    process.terminate()
    raise RuntimeError(f"server on port {port} did not become ready")


def stop_server(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        process.kill()


def show(label: str, response: httpx.Response, body: Any = None) -> None:
    print(f"\n--- {label} ---")
    print(f"HTTP {response.status_code}")
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower().startswith("x-") or key.lower() == "content-type"
    }
    print("headers:", json.dumps(headers, ensure_ascii=False, indent=2))
    if body is not None:
        print("body:", json.dumps(body, ensure_ascii=False, indent=2)[:1600])


def scenario_healthy() -> List[str]:
    checks: List[str] = []
    process = start_server(HEALTHY_PORT, {"MOCK_FAIL_MODE": "none"})
    base = f"http://127.0.0.1:{HEALTHY_PORT}"
    try:
        with httpx.Client(base_url=base, timeout=30) as client:
            banner("0. Health check")
            health = client.get("/health")
            print(f"HTTP {health.status_code}")
            print(json.dumps(health.json(), ensure_ascii=False, indent=2)[:1200])

            banner("1. Valid request -> successful answer")
            first = client.post(API_PATH, json=PAYLOAD)
            first_body = first.json()
            show("POST /api/v1/qa (first call)", first, first_body)
            checks.append(f"success: HTTP {first.status_code}, degraded={first_body['degraded']}")

            banner("2. Repeated request -> cache hit")
            second = client.post(API_PATH, json=PAYLOAD)
            second_body = second.json()
            show("POST /api/v1/qa (repeat call)", second, second_body)
            print(
                f"\nlatency: first={first_body['latency_ms']} ms, "
                f"cached={second_body['latency_ms']} ms"
            )
            checks.append(
                f"cache: X-Cache={second.headers.get('X-Cache')}, cached={second_body['cached']}"
            )

            banner("3. Invalid request -> HTTP 422")
            invalid = client.post(API_PATH, json={**PAYLOAD, "question": "  "})
            show("POST /api/v1/qa (blank question)", invalid, invalid.json())
            checks.append(f"validation: HTTP {invalid.status_code}")
            return checks
    finally:
        stop_server(process)


def scenario_outage() -> List[str]:
    checks: List[str] = []
    process = start_server(FAULTY_PORT, {"MOCK_FAIL_MODE": "error"})
    base = f"http://127.0.0.1:{FAULTY_PORT}"
    try:
        with httpx.Client(base_url=base, timeout=30) as client:
            banner("4. LLM outage -> extractive fallback (HTTP 200, degraded=true)")
            response = client.post(API_PATH, json=PAYLOAD)
            body = response.json()
            show("POST /api/v1/qa (provider is down)", response, body)
            checks.append(
                f"fallback: HTTP {response.status_code}, degraded={body['degraded']}, "
                f"reason={body['degradation_reason']}"
            )

            banner("5. LLM outage + allow_fallback=false -> HTTP 503")
            strict = client.post(API_PATH, json={**PAYLOAD, "allow_fallback": False})
            show("POST /api/v1/qa (strict mode)", strict, strict.json())
            checks.append(f"strict: HTTP {strict.status_code}")
            return checks
    finally:
        stop_server(process)


def main() -> int:
    print("docqa-service demo — mock LLM provider, no API key or network required")
    checks = scenario_healthy() + scenario_outage()
    banner("Summary")
    for check in checks:
        print(f"  [ok] {check}")
    print("\nAll demo scenarios completed.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
