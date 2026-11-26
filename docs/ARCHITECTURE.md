# Архитектура docqa-service

Документ описывает слои, поток данных, обработку ошибок, кеширование и точки
расширения. Он рассчитан на ревьюера, который открывает PR и хочет быстро понять,
почему код разложен именно так.

## 1. Цели и ограничения

* Один пользовательский сценарий: **вопрос по документу** (extractive retrieval +
  генерация ответа LLM).
* Сервис не хранит документы: контекст передаётся в запросе.
* Один инстанс, in-memory кеш — учебный production-like вариант; Redis вынесен в
  точки расширения.
* Работает без API-ключа (mock-провайдер) — это важно для CI, демо и проверки.

## 2. Слои

| Слой | Пакет | Ответственность | Не знает о |
|---|---|---|---|
| HTTP API | `docqa.api` | маршруты, Pydantic-схемы, статусы, заголовки, `request_id`, лимит тела | промптах, провайдерах, кеше |
| Бизнес-логика | `docqa.services` | пайплайн, валидация бизнес-лимитов, кеш, fallback, пост-обработка | HTTP, конкретном LLM-вендоре |
| LLM | `docqa.llm` | промпты, вызов модели, таймауты, ретраи, нормализация ответа | HTTP-слое, кеше |
| Инфраструктура | `docqa.core` | конфигурация, логирование, ошибки, TTL-кеш, метрики | бизнес-сценарии |
| Точка входа | `main.py`, `cli.py` | сборка зависимостей (composition root), ASGI/CLI | — |

Правило зависимостей: `api → services → llm → core`. Обратных импортов нет.
`QAService` зависит от протокола `LLMClient`, а не от `OpenAIChatClient`, поэтому
провайдер подменяется в тестах без сети.

## 3. Компоненты

```
Client
  │  POST /api/v1/qa
  ▼
RequestContextMiddleware ── request_id (contextvar), Content-Length guard, access log
  ▼
api/routes.ask ── Pydantic QARequest (extra=forbid, blank/format check)
  ▼
QAService.answer
  ├─ _validate_question / _validate_context   (limits из Settings → 422)
  ├─ TTLCache.get                             (hit → cached result, X-Cache: HIT)
  ├─ retrieval.select_excerpts                (TF-IDF, top_k, max_chars)
  ├─ prompts.build_llm_request                (system + user, нумерованные фрагменты)
  ├─ LLMClient.generate                       (timeout, retries, typed errors)
  ├─ postprocess.clean_answer                 (префиксы, fences, пробелы, длина)
  ├─ TTLCache.set                             (только успешные ответы)
  └─ QAResult → api/schemas.QAResponse
  ▼
Client (answer, citations, degraded, cached, usage, latency_ms)
```

### 3.1. Ретривер

`services/retrieval.py`:

1. Склеивает жёсткие переносы строк, но сохраняет границы абзацев, списков и
   заголовков.
2. Делит текст на предложения.
3. Считает IDF по предложениям и взвешивает пересечение токенов вопроса и
   предложения; нормирует на `sqrt(len)`.
4. Отбирает `top_k` предложений в пределах `MAX_EXCERPT_CHARS`.

Возвращаемые фрагменты — одновременно цитаты в ответе, материал для промпта и
источник экстрактивного fallback. Порядок — по релевантности, поэтому номера
`[1..k]` в промпте совпадают с `citations[].index`.

### 3.2. LLM-слой

* `llm/prompts.py` — единственное место формирования промптов (system: отвечать
  только по контексту, не выдумывать; user: нумерованные фрагменты + вопрос).
* `llm/providers/mock.py` — офлайн-провайдер, умеет имитировать `timeout`, `error`,
  `empty`.
* `llm/providers/openai_compat.py` — `/chat/completions` с `Authorization: Bearer`,
  таймаутом и ретраями. Ретраятся таймауты, сетевые ошибки, 429 и 5xx; 4xx (кроме
  429) не ретраятся и сразу превращаются в `LLMBadResponseError`.
* `llm/factory.py` — единственная точка выбора провайдера по конфигурации.

### 3.3. Пост-обработка

`services/postprocess.py` убирает `Answer:`/`Ответ:`, markdown-заборы, хвостовые
пробелы, схлопывает пустые строки, обрезает по границе предложения. Пустой
результат — `PostprocessingError`, который запускает тот же fallback, что и сбой
провайдера.

## 4. Обработка ошибок

Иерархия в `core/errors.py`: `AppError` → `InvalidInputError`, `LLMError`
(`LLMTimeoutError`, `LLMUnavailableError`, `LLMRateLimitError`,
`LLMBadResponseError`), `PostprocessingError`, `ConfigurationError`.

| Ситуация | Внутренняя ошибка | HTTP (fallback разрешён) | HTTP (fallback запрещён) |
|---|---|---|---|
| Пустой/длинный вопрос, пустой/длинный документ | `InvalidInputError` | 422 | 422 |
| Провайдер недоступен (5xx, сеть) | `LLMUnavailableError` | 200 + `degraded=true` | 503 |
| Таймаут | `LLMTimeoutError` | 200 + `degraded=true` | 504 |
| 429 после ретраев | `LLMRateLimitError` | 200 + `degraded=true` | 429 |
| Битый ответ модели | `LLMBadResponseError` | 200 + `degraded=true` | 502 |
| Пустой ответ после очистки | `PostprocessingError` | 200 + `degraded=true` | 502 |
| Тело > лимита | middleware | 413 | 413 |
| Непредвиденная ошибка | `Exception` | 500, детали только в логе | 500 |

Fallback собирает ответ из двух наиболее релевантных предложений документа. Такие
ответы **не кешируются**, чтобы после восстановления провайдера следующий запрос
снова пошёл в LLM.

## 5. Кеширование

* Класс `core/cache.TTLCache`: `OrderedDict`, `threading.Lock`, TTL и LRU-эвикция,
  счётчики hits/misses/expired/evictions, инъекция часов для детерминированных
  тестов.
* Ключ: SHA-256 от версии пайплайна, имени провайдера, модели, нормализованного
  вопроса, нормализованного документа и `top_k`. `allow_fallback` в ключ не входит:
  успешный ответ от него не зависит.
* TTL (`CACHE_TTL_SECONDS`) и размер (`CACHE_MAX_ENTRIES`) — только из конфигурации.
* Каждое обращение логируется: `cache_hit` (INFO) / `cache_miss` (DEBUG), а также
  отражается в `cached`, `X-Cache` и `/health.cache`.

## 6. Конфигурация

`core/config.Settings` (pydantic-settings) — типизированные поля, валидаторы и
кросс-валидация:

* в `APP_ENV=prod` запрещён `LLM_PROVIDER=mock`;
* `LLM_PROVIDER=openai` требует непустой `LLM_API_KEY`;
* лимиты `MAX_QUESTION_CHARS`/`MAX_EXCERPT_CHARS` согласованы между собой;
* ключ — `SecretStr`, есть `safe_dict()` для логов.

Приоритет источников: OS env → `config/<APP_ENV>.env` → `.env` → defaults.
`config/dev.env` и `config/prod.env` коммитятся, секретов не содержат.

## 7. Наблюдаемость

* JSON-логи (`APP_LOG_FORMAT=json`) с уровнями INFO/WARNING/ERROR.
* `request_id` через `contextvars`, поэтому его видят все слои и заголовок ответа.
* События: `request_received`, `cache_hit|miss`, `prompt_built`, `model_response`,
  `llm_call_failed`, `fallback_used`, `postprocessing_failed`, `answer_ready`,
  `request_completed`, `app_error`.
* `/health` отдаёт uptime, состояние кеша и счётчики (`requests_total`,
  `llm_calls`, `llm_errors`, `fallbacks`, `cache_hits`, `answers_ok`).

## 8. Тестируемость и точки расширения

* `create_app(settings, llm_client=...)` — DI-точка: тесты подставляют `StubLLMClient`.
* `QAService(..., cache=..., metrics=..., clock=...)` — управляемые TTL и метрики.
* `TTLCache` можно заменить Redis-реализацией с тем же интерфейсом (`get/set/stats`).
* `LLMClient` — протокол: добавление нового провайдера не трогает бизнес-логику.
* Ретривер изолирован: замена на эмбеддинги не влияет на API и LLM-слой.

## 9. Осознанные компромиссы

* In-memory кеш и метрики — простота и нулевые зависимости; для нескольких реплик
  нужен Redis/Prometheus.
* Лексический ретривер дешёв и детерминирован, но уступает эмбеддингам на
  перефразированных вопросах.
* Нет аутентификации/rate limiting: предполагается, что сервис стоит за API-gateway.
* Промпт-версия участвует в ключе кеша (`qa-pipeline-v1`) — при изменении промптов
  её нужно инкрементировать.
