SHELL := /bin/bash
.ONESHELL:

# Load finalkpi/.env into the API process when it exists (Groq key, LLM pricing).
ENV_FILE_ARG := $(if $(wildcard .env),--env-file .env,)

.PHONY: dev backend frontend test-engine test-backend typecheck

# Start the API and Next.js dashboard together. Ctrl+C stops both processes.
dev:
	set -euo pipefail
	.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000 $(ENV_FILE_ARG) &
	backend_pid=$$!
	(cd frontend && npm run dev) &
	frontend_pid=$$!
	trap 'kill $$backend_pid $$frontend_pid 2>/dev/null || true' EXIT INT TERM
	wait -n $$backend_pid $$frontend_pid

backend:
	.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000 $(ENV_FILE_ARG)

frontend:
	cd frontend && npm run dev

test-engine:
	.venv/bin/python -m unittest discover -s tests -p 'test_*.py'

test-backend:
	.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'

typecheck:
	cd frontend && ./node_modules/.bin/tsc --noEmit --incremental false
