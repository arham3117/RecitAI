# RecitAI — see plan/RECITAI_BUILD_SPEC.md §0.3
.PHONY: help dev down lint format test smoke services ingest migrate eval compare api web install

BACKEND := backend
UV      := uv run --project $(BACKEND)

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-10s %s\n", $$1, $$2}'

install:  ## sync the backend virtualenv
	uv sync --project $(BACKEND) --extra dev

dev:  ## start qdrant + postgres (Ollama runs natively — D-002)
	docker compose up -d
	@echo "waiting for healthchecks..."
	@n=0; until [ "$$(docker compose ps --format '{{.Health}}' | grep -c healthy)" = "2" ]; do \
		n=$$((n+1)); \
		if [ $$n -gt 60 ]; then echo "services did not become healthy in 120s:"; docker compose ps; exit 1; fi; \
		sleep 2; \
	done
	@docker compose ps
	@cd $(BACKEND) && uv run python ../scripts/check_services.py

down:  ## stop services
	docker compose down

lint:  ## ruff + black --check + mypy
	$(UV) ruff check $(BACKEND)
	$(UV) black --config $(BACKEND)/pyproject.toml --check $(BACKEND) scripts
	$(UV) mypy --config-file $(BACKEND)/pyproject.toml $(BACKEND)/recitai $(BACKEND)/tests scripts

format:  ## apply ruff --fix and black
	$(UV) ruff check --fix $(BACKEND)
	$(UV) black --config $(BACKEND)/pyproject.toml $(BACKEND) scripts

test:  ## pytest
	cd $(BACKEND) && uv run pytest -q

services:  ## verify postgres + qdrant are reachable and are the right instances
	cd $(BACKEND) && uv run python ../scripts/check_services.py

web:  ## run the Next.js frontend on :3000 (needs `make api`)
	cd frontend && npm run dev

api:  ## run the API on :8000
	cd $(BACKEND) && uv run uvicorn recitai.api.main:app --reload --port 8000

smoke:  ## Phase 0 gate: structured output + embedding against the real models
	cd $(BACKEND) && uv run python ../scripts/smoke_test.py

ingest:  ## ingest a file or directory: make ingest F=materials C="Distributed DBs"
	cd $(BACKEND) && uv run recitai ingest ../$(F) --course "$(C)"

migrate:  ## apply database migrations
	cd $(BACKEND) && uv run alembic upgrade head

eval:  ## metrics report (spec §15)
	cd $(BACKEND) && uv run python ../eval/run_eval.py

reconcile:  ## check qdrant/postgres agree (add FIX=1 to clean up orphans)
	cd $(BACKEND) && uv run python ../scripts/reconcile_vectors.py $(if $(FIX),--fix,)

compare:  ## compare generation runs: make compare LOGS="a.txt b.txt"
	cd $(BACKEND) && uv run python ../eval/compare_runs.py $(LOGS)
