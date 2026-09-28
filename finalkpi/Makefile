SHELL := /bin/bash
.ONESHELL:
.DEFAULT_GOAL := help

# Load finalkpi/.env into the API process when it exists (Groq key, LLM pricing).
ENV_FILE_ARG := $(if $(wildcard .env),--env-file .env,)
PY := PYTHONPATH=. .venv/bin/python

.PHONY: help setup dev backend frontend demo stop reset test test-engine test-backend test-frontend typecheck eval build

help: ## Show available commands
	@echo "KPI engine: common commands (run from finalkpi/)"
	@echo
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-14s %s\n", $$1, $$2}'
	@echo
	@echo "Website: http://127.0.0.1:3000   API: http://127.0.0.1:8000/health"

setup: ## One-time install of Python and frontend dependencies
	set -euo pipefail
	[ -d .venv ] || python3 -m venv .venv
	.venv/bin/pip install -q -e '.[dev,rag]'
	cd frontend && npm install

# Start the API and Next.js dashboard together. Ctrl+C stops both processes.
dev: ## Start API + website (development mode, live reload)
	set -euo pipefail
	.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000 $(ENV_FILE_ARG) &
	backend_pid=$$!
	(cd frontend && npm run dev) &
	frontend_pid=$$!
	trap 'kill $$backend_pid $$frontend_pid 2>/dev/null || true' EXIT INT TERM
	echo "Website: http://127.0.0.1:3000  (Ctrl+C to stop)"
	wait -n $$backend_pid $$frontend_pid

demo: ## Start API + production build (faster pages, for presenting)
	set -euo pipefail
	(cd frontend && npm run build)
	.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000 $(ENV_FILE_ARG) &
	backend_pid=$$!
	(cd frontend && npm run start) &
	frontend_pid=$$!
	trap 'kill $$backend_pid $$frontend_pid 2>/dev/null || true' EXIT INT TERM
	echo "Website: http://127.0.0.1:3000  (Ctrl+C to stop)"
	wait -n $$backend_pid $$frontend_pid

backend: ## Start only the API
	.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000 $(ENV_FILE_ARG)

frontend: ## Start only the website
	cd frontend && npm run dev

# Bracketed patterns stop pkill from matching this recipe's own shell.
stop: ## Stop an API/website left running in the background
	@-pkill -f "[u]vicorn backend.app:app" && echo "API stopped" || echo "API not running"
	@-pkill -f "[n]ext (dev|start)" && echo "Website stopped" || echo "Website not running"

reset: ## Clear cached diagnosis runs (stop the app first)
	@rm -f backend/runtime/kpi_backend.sqlite3
	echo "Cached runs cleared; the next diagnosis is recomputed."

test: test-engine test-backend test-frontend typecheck ## Run all test suites

test-engine: ## Engine tests
	$(PY) -m unittest discover -s tests -p 'test_*.py'

test-backend: ## Backend/API tests
	$(PY) -m unittest discover -s backend/tests -p 'test_*.py'

test-frontend: ## Frontend unit tests
	cd frontend && npm test

typecheck: ## TypeScript check
	cd frontend && ./node_modules/.bin/tsc --noEmit --incremental false

eval: ## Ground-truth scoreboard (all 538 cases)
	$(PY) tests/run_ground_truth_eval.py --split all --markdown-out /tmp/kpi_eval.md > /dev/null
	cat /tmp/kpi_eval.md

build: ## Check the frontend production build
	cd frontend && npm run build
