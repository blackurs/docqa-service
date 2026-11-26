# Pull Request: docqa-service — LLM Q&A сервис с CI, конфигурацией и fallback

## Цель изменений

Добавить end-to-end LLM-сервис для ответов на вопросы по документу, оформленный
как production-like решение: слоистая архитектура, валидация, обработка ошибок
внешнего вызова, fallback, TTL-кеш, структурированные логи, конфигурация через
переменные окружения, безопасная работа с секретами, CI и полная документация.

## Что реализовано

### Архитектура

* `api/` — FastAPI-маршруты, Pydantic-схемы, middleware (`request_id`, лимит тела),
  единый формат ошибок.
* `services/` — `QAService` (пайплайн), `retrieval` (ранжирование фрагментов),
  `postprocess` (очистка ответа).
* `llm/` — контракт `LLMClient`, промпты, провайдеры `mock` и `openai_compat`
  (любой OpenAI-совместимый API), фабрика.
* `core/` — типизированная конфигурация, JSON-логи, иерархия ошибок, TTL+LRU кеш,
  метрики.
* `main.py` / `cli.py` — composition root, ASGI и CLI (`serve`, `ask`).

### Функциональность

* `POST /api/v1/qa`: вопрос + документ → ответ + цитаты + метаданные.
* Валидация: Pydantic (`extra=forbid`, blank-check) + бизнес-лимиты из конфигурации.
* Ретраи с экспоненциальной задержкой для таймаутов, 429 и 5xx; типизированные
  ошибки провайдера.
* Fallback: HTTP 200 + `degraded=true` + экстрактивный ответ; строгий режим
  (`allow_fallback=false`) возвращает 503/504/429/502.
* Кеш: ключ учитывает вопрос, документ, модель и `top_k`; TTL и LRU; заголовок
  `X-Cache`; логи `cache_hit`/`cache_miss`; fallback-ответы не кешируются.
* Логи: JSON, уровни INFO/WARNING/ERROR, сквозной `request_id`, этапы запроса,
  промпта, ответа и ошибок.
* `/health` — кеш и счётчики; `/ready` — readiness-проба.

### Инфраструктура и качество

* `.env.example` (шаблон), `.env` в `.gitignore`, `SecretStr` для API-ключа,
  разделение `config/dev.env` и `config/prod.env`.
* GitHub Actions: ruff, pytest на Python 3.9/3.11/3.12, `pip check`, импорт
  приложения, сборка wheel/sdist, `docker build`.
* Dockerfile (non-root, healthcheck) и `docker-compose.yml`.
* `run.bat` / `run.sh` — запуск одной командой; `Makefile` для типовых задач.
* 99 тестов; `scripts/demo.py` — сквозное демо всех сценариев.
* README, `docs/ARCHITECTURE.md`, `TESTING.md`, `PULL_REQUEST.md`.

## Как проверить

```bash
# 1. Установка и тесты
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pip install -e .
pytest -q                            # 99 passed
ruff check . && ruff format --check .

# 2. Запуск
cp .env.example .env                 # mock-провайдер, ключ не нужен
python -m docqa.cli serve

# 3. Демо всех сценариев (success, cache, 422, fallback, 503)
python scripts/demo.py
```

## Результаты проверки

| Сценарий | Ожидание | Факт |
|---|---|---|
| Валидный запрос | 200, `degraded=false`, есть цитаты | ✅ 200, `mock/mock-qa-1`, 3 цитаты |
| Повторный запрос | `X-Cache: HIT`, `cached=true`, быстрее | ✅ 0.105 ms против 40.667 ms |
| Пустой вопрос | 422 `validation_error` | ✅ 422, `field=body.question` |
| Сбой LLM | 200, `degraded=true`, fallback | ✅ `reason=llm_unavailable`, `X-Degraded: true` |
| Сбой LLM + strict | 503 `llm_unavailable` | ✅ 503 |
| Тесты | Все зелёные | ✅ 99 passed |
| Линтер | Без замечаний | ✅ ruff check / format |

Подробные выводы: [`TESTING.md`](TESTING.md).

## Чек-лист самопроверки

- [x] Сервис запускается одной командой (`run.bat` / `run.sh` / `docker run`)
- [x] README содержит описание, установку, запуск, API и примеры
- [x] Структура репозитория логична (`api/`, `services/`, `llm/`, `core/`, `tests/`)
- [x] Валидация входных данных и понятные ошибки (422 + `details`)
- [x] Обработка сетевых ошибок, таймаутов и 429/5xx с ретраями
- [x] Fallback при недоступности модели; строгий режим возвращает корректный статус
- [x] Кеш с TTL, корректным ключом, логированием hit/miss
- [x] Логи ключевых этапов с уровнями и `request_id`
- [x] Настройки только через переменные окружения, без хардкода URL/ключей/таймаутов
- [x] `.env` не в репозитории, есть `.env.example`, секреты замаскированы
- [x] CI настроен: линтер, тесты, проверка установки, сборка, Docker
- [x] Тесты покрывают успех, валидацию, fallback, кеш, ретраи и пост-обработку
- [x] Есть демо-скрипт и зафиксированные результаты тестирования
- [x] PR содержит цель, архитектуру и чек-лист

## Риски и ограничения

* Кеш и метрики in-process: для нескольких реплик нужны Redis/Prometheus.
* Ретривер лексический: на перефразированных вопросах уступает эмбеддингам.
* Нет аутентификации/rate limiting на уровне приложения (предполагается gateway).
* CI-workflow добавлен, но не запускался на GitHub до пуша; локально выполнены те
  же команды (ruff + pytest + установка пакета).

## Как создать PR

```bash
git init
git add .
git commit -m "feat: add docqa-service with CI, config and fallback"
git branch -M main
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main

git checkout -b feature/docqa-service
git push -u origin feature/docqa-service
gh pr create --base main --head feature/docqa-service \
  --title "feat: docqa-service — LLM Q&A с CI, конфигурацией и fallback" \
  --body-file PULL_REQUEST.md
```

Без `gh`: откройте ссылку из вывода `git push` и вставьте содержимое этого файла в
описание PR.
