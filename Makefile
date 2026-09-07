# Japan Second Trip
.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash
PY := ./.venv/bin

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: setup
setup: ## Create the Python env and install everything
	python3.12 -m venv .venv
	$(PY)/pip install --upgrade pip
	$(PY)/pip install -e ./packages/shared_schemas -e ./packages/travel_mcp -e "./apps/backend[dev]"
	cd apps/frontend && npm install --no-audit --no-fund

.PHONY: dev
dev: ## Start database, API and web
	./scripts/dev.sh

.PHONY: reset
reset: ## Drop the database, migrate and re-seed
	./scripts/dev.sh --reset

.PHONY: migrate
migrate: ## Apply database migrations
	cd apps/backend && ../../$(PY)/alembic upgrade head

.PHONY: seed
seed: ## Seed the demo catalogue and evidence
	$(PY)/python scripts/seed.py

.PHONY: test
test: ## Run the backend test suite
	$(PY)/python -m pytest apps/backend/tests -q

.PHONY: test-cov
test-cov: ## Backend tests with a coverage report
	$(PY)/python -m pytest apps/backend/tests -q --cov=jst_api --cov-report=term-missing

.PHONY: test-web
test-web: ## Frontend unit tests
	npm --prefix apps/frontend test

.PHONY: e2e
e2e: ## Playwright end-to-end tests (needs the stack running)
	cd apps/frontend && npx playwright test

.PHONY: lint
lint: ## Lint and type-check everything
	./scripts/check.sh

.PHONY: format
format: ## Auto-format Python
	$(PY)/ruff format apps/backend/src apps/backend/tests evals packages scripts
	$(PY)/ruff check --fix apps/backend/src apps/backend/tests evals packages scripts

.PHONY: evals
evals: ## Run every eval suite
	$(PY)/python -m evals.run all

.PHONY: evals-ci
evals-ci: ## Run the fast CI eval subset
	$(PY)/python -m evals.run ci

.PHONY: sweep
sweep: ## Retrieval hyper-parameter sweep
	$(PY)/python -m evals.runners.sweep

.PHONY: mcp
mcp: ## Run the MCP gateway on stdio for an external client
	$(PY)/travel-intelligence-mcp

.PHONY: up
up: ## Whole stack in Docker
	docker compose up --build

.PHONY: down
down: ## Stop the stack
	docker compose down

.PHONY: clean
clean: ## Remove build and cache artefacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache apps/frontend/.next apps/frontend/test-results
