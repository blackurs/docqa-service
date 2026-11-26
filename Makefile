PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help install run test lint format check demo docker-build clean

help:
	@echo "install      create venv and install dev dependencies"
	@echo "run          start the API on APP_HOST:APP_PORT"
	@echo "test         run the test suite"
	@echo "lint         ruff check + format check"
	@echo "format       auto-format and auto-fix"
	@echo "check        lint + tests (what CI runs)"
	@echo "demo         end-to-end demo (success, validation, fallback, cache)"
	@echo "docker-build build the Docker image"

install:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -r requirements-dev.txt
	$(BIN)/python -m pip install -e .
	@if [ ! -f .env ]; then cp .env.example .env; echo "created .env from .env.example"; fi

run:
	$(BIN)/python -m docqa.cli serve

test:
	$(BIN)/python -m pytest

lint:
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format:
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

check: lint test

demo:
	$(BIN)/python scripts/demo.py

docker-build:
	docker build -t docqa-service:local .

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache build dist *.egg-info
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
