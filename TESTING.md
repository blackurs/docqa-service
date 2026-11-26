# Отчёт о тестировании и подтверждение работоспособности

Дата прогона: **2026-11-26**. Все результаты ниже получены на реально запущенном
сервисе (mock-провайдер, без внешней сети и API-ключа), а не сформулированы
«по памяти».

## 1. Окружение

| Компонент | Версия |
|---|---|
| ОС | Windows 11 (x64) |
| Python (основной прогон) | 3.14.5 |
| Python (проверка совместимости) | 3.9.25 |
| pytest / pytest-asyncio | 9.2.0 / 1.5.0 |
| ruff | 0.17.6 |
| FastAPI | 0.165.0 |
| pydantic / pydantic-settings | 2.14.4 / 2.16.3 |
| httpx | 0.28.1 |
| uvicorn | 0.54.0 |

## 2. Автоматические проверки

```text
$ pytest -q
99 passed in 0.59s

$ .venv39\Scripts\python.exe -m pytest -q     # Python 3.9.25
99 passed in 0.85s

$ ruff check .
All checks passed!

$ ruff format --check .
All checked files are formatted

$ pip check
No broken requirements found.

$ python -m build
Successfully built docqa_service-1.0.0.tar.gz and docqa_service-1.0.0-py3-none-any.whl

$ python scripts/demo.py
... All demo scenarios completed.   (exit code 0)
```

Что покрывают тесты:

| Файл | Проверяет |
|---|---|
| `tests/test_config.py` | значения по умолчанию, env-override, приоритет env-файлов, запрет mock в prod, обязательный ключ, маскирование секрета, фабрику провайдеров |
| `tests/test_cache.py` | hit/miss, TTL, purge, LRU-эвикцию, статистику, стабильность ключа |
| `tests/test_retrieval.py` | разбиение на предложения (включая жёсткие переносы и списки), ранжирование, лимиты `top_k`/`max_chars`, пустой документ |
| `tests/test_postprocess.py` | префиксы `Answer:`/`Ответ:`, markdown-заборы, пробелы, пустой ответ, обрезку |
| `tests/test_prompts.py` | нумерацию фрагментов, подстановку настроек, анти-галлюцинационные правила |
| `tests/test_mock_provider.py` | детерминированные ответы и имитацию сбоев |
| `tests/test_openai_provider.py` | успешный вызов, заголовок авторизации, ретраи на 5xx/429/таймаут, отсутствие ретраев на 401, битый JSON |
| `tests/test_api.py` | `/health`, `/ready`, успех, `request_id`, кеш, 413, 422 (9 вариантов), fallback, strict 503, пустой ответ модели |
| `tests/test_service.py` | кеш не вызывает LLM повторно, истечение TTL, fallback не кешируется, метрики, валидация, `top_k` |

## 3. Приёмочные сценарии

| № | Сценарий | Ожидание | Фактический результат | Статус |
|---|---|---|---|---|
| 1 | Валидный запрос | 200, ответ и цитаты, `degraded=false` | 200, `mock/mock-qa-1`, 3 цитаты, `X-Cache: MISS` | ✅ |
| 2 | Повторный запрос | `X-Cache: HIT`, `cached=true`, быстрее | HIT, 0.105 ms против 40.667 ms, LLM не вызывался | ✅ |
| 3 | Ошибка ввода (пустой вопрос) | 422 `validation_error` | 422, `field=body.question`, `reason=must not be blank` | ✅ |
| 4 | Сбой внешнего вызова | 200, `degraded=true`, fallback | 200, `reason=llm_unavailable`, `X-Degraded: true` | ✅ |
| 5 | Сбой внешнего вызова + `allow_fallback=false` | 503 `llm_unavailable` | 503, без `X-Degraded` | ✅ |
| 6 | Сборка/линт/тесты | Без ошибок | см. раздел 2 | ✅ |

## 4. Фактические выводы

### 4.1. Успешный запрос (сценарий 1)

Запрос:

```json
{
  "question": "Сколько секунд таймаут по умолчанию и сколько повторных попыток?",
  "context": "<содержимое data/sample_document.txt>",
  "top_k": 3
}
```

Ответ (фрагмент реального вывода `python scripts/demo.py`):

```http
HTTP/1.1 200 OK
content-type: application/json
x-cache: MISS
x-request-id: 1e5c236935ad49d4a45ad6215e3c3c78
```

```json
{
  "request_id": "1e5c236935ad49d4a45ad6215e3c3c78",
  "answer": "По умолчанию клиент LLM использует таймаут 20 секунд. Результаты успешных ответов кешируются на 300 секунд по умолчанию (CACHE_TTL_SECONDS).",
  "citations": [
    {
      "index": 1,
      "text": "По умолчанию клиент LLM использует таймаут 20 секунд.",
      "score": 3.1656
    },
    {
      "index": 2,
      "text": "Результаты успешных ответов кешируются на 300 секунд по умолчанию (CACHE_TTL_SECONDS).",
      "score": 1.9741
    },
    {
      "index": 3,
      "text": "При сетевой ошибке, таймауте, ответе 429 или 5xx сервис выполняет до двух повторных попыток с экспоненциальной задержкой (LLM_MAX_RETRIES=2, LLM_RETRY_BACKOFF_SECONDS=0.5).",
      "score": 1.651
    }
  ],
  "degraded": false,
  "degradation_reason": null,
  "cached": false,
  "provider": "mock",
  "model": "mock-qa-1",
  "latency_ms": 40.611,
  "usage": {"prompt_tokens": 192, "completion_tokens": 35}
}
```

> `latency_ms` включает искусственную задержку mock-провайдера `MOCK_LATENCY_MS=40`,
> чтобы наглядно показать эффект кеша. С реальным LLM задержка определяется сетью и
> моделью.

### 4.2. Кеш: повторный запрос (сценарий 2)

```http
HTTP/1.1 200 OK
x-cache: HIT
x-request-id: 333778c971c6411a8f563c6952d85a49
```

```json
{
  "cached": true,
  "provider": "mock",
  "latency_ms": 0.105,
  "answer": "По умолчанию клиент LLM использует таймаут 20 секунд. ..."
}
```

Сравнение из демо: `first=40.667 ms, cached=0.105 ms`. Провайдер повторно не
вызывался (это отдельно проверяет `test_repeat_request_is_served_from_cache`:
`stub.calls == 1`).

### 4.3. Ошибка валидации (сценарий 3)

```http
HTTP/1.1 422 Unprocessable Entity
x-request-id: 732ef37a26e145ae8c9dc802eb6862d3
```

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request payload failed validation",
    "details": [
      {
        "field": "body.question",
        "reason": "Value error, must not be blank",
        "type": "value_error"
      }
    ],
    "request_id": "732ef37a26e145ae8c9dc802eb6862d3"
  }
}
```

Также покрыты: отсутствие обязательного поля, неизвестное поле (`extra=forbid`),
превышение `MAX_QUESTION_CHARS`/`MAX_CONTEXT_CHARS`, тело больше лимита (413).

### 4.4. Сбой LLM → fallback (сценарий 4)

Сервис запущен с `MOCK_FAIL_MODE=error` (имитация недоступности провайдера).

```http
HTTP/1.1 200 OK
x-cache: MISS
x-degraded: true
x-degradation-reason: llm_unavailable
x-request-id: f7ee8361518a4b539dca255136c2e575
```

```json
{
  "answer": "По умолчанию клиент LLM использует таймаут 20 секунд. Результаты успешных ответов кешируются на 300 секунд по умолчанию (CACHE_TTL_SECONDS).",
  "degraded": true,
  "degradation_reason": "llm_unavailable",
  "provider": "extractive",
  "model": "extractive-fallback",
  "usage": {"prompt_tokens": 0, "completion_tokens": 0}
}
```

Ответ собран из наиболее релевантных предложений документа; такой результат **не
попадает в кеш** (проверено `test_fallback_is_not_cached`).

### 4.5. Строгий режим без fallback (сценарий 5)

```http
HTTP/1.1 503 Service Unavailable
```

```json
{
  "error": {
    "code": "llm_unavailable",
    "message": "Mock provider simulated an outage",
    "request_id": "4fb1cdfd9f7d4b02a413f5c5175d7335"
  }
}
```

### 4.6. CLI

```text
$ python -m docqa.cli ask -f data/sample_document.txt \
    -q "Сколько секунд таймаут по умолчанию?"

Answer (mock/mock-qa-1):
По умолчанию клиент LLM использует таймаут 20 секунд. Результаты успешных ответов кешируются на 300 секунд по умолчанию

Sources:
  [1] (score=3.7448) По умолчанию клиент LLM использует таймаут 20 секунд.
  [2] (score=2.4965) Результаты успешных ответов кешируются на 300 секунд по умолчанию
  [3] (score=2.3353) Таймаут настраивается
  [4] (score=0.0) # docqa-service — пример документа для демонстрации

latency_ms=0.709
```

Невалидный ввод в CLI:

```text
$ python -m docqa.cli ask -f data/sample_document.txt -q "да"
Validation error: Question must contain at least 3 characters
$ echo $?
2
```

## 5. Логи ключевых этапов

Реальные строки (JSON, `APP_LOG_FORMAT=json`, фрагменты):

```json
{"ts":"2026-11-26T08:48:25.481+00:00","level":"INFO","logger":"docqa.services.qa_service","message":"request_received","event":"request_received","question_chars":36,"context_chars":1316}
{"ts":"...","level":"INFO","logger":"docqa.services.qa_service","message":"prompt_built","event":"prompt_built","question_chars":36,"context_chars":347,"excerpts":4}
{"ts":"...","level":"INFO","logger":"docqa.services.qa_service","message":"model_response","event":"model_response","provider":"mock","model":"mock-qa-1"}
{"ts":"...","level":"INFO","logger":"docqa.services.qa_service","message":"answer_ready","event":"answer_ready","duration_ms":1.25,"provider":"mock","model":"mock-qa-1","degraded":false}
{"ts":"...","level":"INFO","logger":"docqa.services.qa_service","message":"cache_hit","event":"cache_hit","duration_ms":0.111,"cache":"hit"}
{"ts":"...","level":"ERROR","logger":"docqa.services.qa_service","message":"llm_call_failed","event":"llm_call_failed","provider":"mock","error_code":"llm_unavailable"}
{"ts":"...","level":"WARNING","logger":"docqa.services.qa_service","message":"fallback_used","event":"fallback_used","duration_ms":0.475,"provider":"extractive","model":"extractive-fallback","error_code":"llm_unavailable","degraded":true}
```

По `request_id` восстанавливается вся цепочка обработки одного запроса, включая
HTTP-middleware (`request_started`/`request_completed`).

## 6. Как воспроизвести

```bash
# окружение
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pip install -e .

# автотесты и линт
pytest -q
ruff check .
ruff format --check .

# сквозное демо (само поднимает и останавливает сервер)
python scripts/demo.py

# ручной запуск и curl
cp .env.example .env
python -m docqa.cli serve
```

## 7. CI

Workflow: [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

| Job | Что делает |
|---|---|
| `lint` | `ruff check .` + `ruff format --check .` |
| `test` | Python 3.9/3.11/3.12: установка `requirements-dev.txt` и пакета, `pip check`, импорт `docqa.main:app`, `pytest -q`, сборка wheel/sdist |
| `docker` | `docker build` |

Локально выполнены те же команды (см. разделы 2 и 4), все зелёные. Docker-демон на
машине разработчика отсутствует, поэтому образ проверяется job'ом `docker` после
пуша в GitHub. Прогон workflow в GitHub Actions выполняется автоматически при
создании PR.

## 8. Скриншоты / видео

Для сдачи можно приложить скриншоты (папка `docs/screenshots/`, в Git не входят
артефакты прогонов — только изображения):

1. `01-success.png` — ответ 200 в Swagger UI или curl;
2. `02-cache-hit.png` — повторный запрос с `X-Cache: HIT`;
3. `03-validation.png` — 422 на пустой вопрос;
4. `04-fallback.png` — 200 + `degraded=true` при `MOCK_FAIL_MODE=error`;
5. `05-ci-green.png` — зелёный прогон GitHub Actions;
6. `06-demo.png` — вывод `python scripts/demo.py`.

Текстовые доказательства из разделов 2–5 самодостаточны и воспроизводятся одной
командой.

## 9. Чек-лист требований задания

- [x] Сервис запускается одной командой (`run.bat`, `run.sh`, `docker run`)
- [x] README с описанием, установкой, API и примерами
- [x] Логичная структура (`api/`, `services/`, `llm/`, `core/`, `tests/`)
- [x] Валидация входных данных и понятные ошибки
- [x] Обработка таймаутов/сетевых ошибок, ретраи
- [x] Fallback при недоступности модели + корректные статусы
- [x] Кеш с корректным ключом и TTL, логи hit/miss
- [x] Логи ключевых этапов с уровнями и `request_id`
- [x] Конфигурация через env, разделение dev/prod, без хардкода
- [x] Секреты не в репозитории, есть `.env.example`, маскирование в логах
- [x] CI с линтером, тестами и проверкой установки/сборки
- [x] Тесты и подтверждение работоспособности (успех, ошибка, fallback, кеш)
- [x] PR-описание, архитектура и чек-лист самопроверки (`PULL_REQUEST.md`)
