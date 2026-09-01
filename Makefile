# RecitAI — see plan/RECITAI_BUILD_SPEC.md §0.3
.PHONY: help dev down lint format test smoke services ingest eval install

BACKEND := backend
UV      := uv run --project $(BACKEND)

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-10s %s\n", $$1, $$2}'

install:  ## sync the backend virtualenv
	uv sync --project $(BACKEND) --extra dev

dev:  ## start qdrant + postgres (Ollama runs natively — D-002)
	docker compose up -d
	@echo "waiting for healthchecks..."
	@until [ "$$(docker compose ps --format '{{.Health}}' | grep -c healthy)" = "2" ]; do sleep 2; done
	@docker compose ps
	@cd $(BACKEND) && uv run python ../scripts/check_services.py

down:  ## stop services
	docker compose down

lint:  ## ruff + black --check + mypy
	$(UV) ruff check $(BACKEND)
	$(UV) black --config $(BACKEND)/pyproject.toml --check $(BACKEND) scripts
	$(UV) mypy $(BACKEND)/recitai

format:  ## apply ruff --fix and black
	$(UV) ruff check --fix $(BACKEND)
	$(UV) black --config $(BACKEND)/pyproject.toml $(BACKEND) scripts

test:  ## pytest
	cd $(BACKEND) && uv run pytest -q

services:  ## verify postgres + qdrant are reachable and are the right instances
	cd $(BACKEND) && uv run python ../scripts/check_services.py

smoke:  ## Phase 0 gate: structured output + embedding against the real models
	cd $(BACKEND) && uv run python ../scripts/smoke_test.py

ingest:  ## ingest a file: make ingest F=materials/1-Introduction.pptx
	@echo "not implemented until Phase 1 (spec §9)"; exit 1

eval:  ## metrics report
	@echo "not implemented until Phase 7 (spec §15)"; exit 1
