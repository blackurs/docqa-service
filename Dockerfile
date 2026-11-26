# syntax=docker/dockerfile:1

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000

WORKDIR /app

# Non-root runtime user.
RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

# Override APP_ENV / LLM_PROVIDER / LLM_API_KEY at runtime:
#   docker run --rm -p 8000:8000 -e APP_ENV=prod -e LLM_PROVIDER=openai \
#     -e LLM_API_KEY=... -e LLM_MODEL=gpt-4o-mini docqa-service
CMD ["uvicorn", "docqa.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
