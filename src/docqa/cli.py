"""Command line interface.

Examples:

    # Run the HTTP service
    python -m docqa.cli serve --port 8000

    # Ask a question from a file (works offline with the mock provider)
    python -m docqa.cli ask \
        --context-file data/sample_document.txt \
        --question "Сколько повторных попыток делает клиент?"

    # Machine-readable output
    python -m docqa.cli ask -f data/sample_document.txt -q "..." --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional, Sequence

from docqa.core.cache import TTLCache
from docqa.core.config import load_settings
from docqa.core.errors import AppError, InvalidInputError
from docqa.core.logging import configure_logging
from docqa.core.metrics import Metrics
from docqa.llm.factory import build_llm_client
from docqa.services.qa_service import QAResult, QAService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docqa",
        description="Document Q&A service (LLM-backed).",
    )
    parser.add_argument(
        "--env",
        dest="app_env",
        default=None,
        help="Configuration environment: dev/test/prod (overrides APP_ENV).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Start the HTTP API with uvicorn.")
    serve.add_argument("--host", default=None, help="Bind host (default: APP_HOST).")
    serve.add_argument("--port", type=int, default=None, help="Bind port (default: APP_PORT).")
    serve.add_argument("--reload", action="store_true", help="Auto-reload on code changes.")

    ask = subparsers.add_parser("ask", help="Ask a single question and print the answer.")
    ask.add_argument("-q", "--question", required=True, help="Question text.")
    source = ask.add_mutually_exclusive_group(required=True)
    source.add_argument("-c", "--context", help="Document text passed inline.")
    source.add_argument("-f", "--context-file", help="Path to a UTF-8 document file.")
    ask.add_argument("--top-k", type=int, default=None, help="Number of excerpts to use.")
    ask.add_argument(
        "--no-fallback",
        action="store_true",
        help="Fail with an error instead of an extractive answer when the LLM is down.",
    )
    ask.add_argument("--json", action="store_true", help="Print the full result as JSON.")
    return parser


def _load_context(args: argparse.Namespace) -> str:
    if args.context is not None:
        return args.context
    path = Path(args.context_file)
    if not path.is_file():
        raise InvalidInputError(
            f"Context file not found: {path}",
            details=[{"field": "context_file", "reason": "not_found"}],
        )
    return path.read_text(encoding="utf-8")


async def _ask(args: argparse.Namespace) -> QAResult:
    settings = load_settings(args.app_env)
    configure_logging(settings.app_log_level, settings.app_log_format)
    context = _load_context(args)
    cache = (
        TTLCache(
            ttl_seconds=settings.cache_ttl_seconds,
            max_entries=settings.cache_max_entries,
        )
        if settings.cache_enabled
        else None
    )
    client = build_llm_client(settings)
    service = QAService(settings, client, cache=cache, metrics=Metrics())
    try:
        return await service.answer(
            question=args.question,
            context=context,
            top_k=args.top_k,
            allow_fallback=not args.no_fallback,
        )
    finally:
        await client.aclose()


def _print_result(result: QAResult, as_json: bool) -> None:
    if as_json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return

    print(f"\nAnswer ({result.provider}/{result.model}):\n{result.answer}\n")
    if result.citations:
        print("Sources:")
        for citation in result.citations:
            print(f"  [{citation.index}] (score={citation.score}) {citation.text}")
    flags = []
    if result.degraded:
        flags.append(f"degraded ({result.degradation_reason})")
    if result.cached:
        flags.append("cached")
    print(f"\nlatency_ms={result.latency_ms} " + ("flags=" + ", ".join(flags) if flags else ""))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args: argparse.Namespace = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        settings = load_settings(args.app_env)
        configure_logging(settings.app_log_level, settings.app_log_format)
        uvicorn.run(
            "docqa.main:app",
            host=args.host or settings.app_host,
            port=args.port or settings.app_port,
            reload=bool(args.reload),
        )
        return 0

    if args.command == "ask":
        try:
            result = asyncio.run(_ask(args))
        except InvalidInputError as exc:
            print(f"Validation error: {exc.message}", file=sys.stderr)
            return 2
        except AppError as exc:
            print(f"Error [{exc.code}]: {exc.message}", file=sys.stderr)
            return 3
        _print_result(result, as_json=bool(args.json))
        return 0

    parser.print_help()
    return 1


__all__: List[str] = ["build_parser", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
