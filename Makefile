.PHONY: help install backend frontend dev check-db install-schema make-test-graph smoke-route bench test test-integration docker-up docker-down lint

help:
	@echo "Targets:"
	@echo "  install            Install backend venv + frontend deps"
	@echo "  backend            Run backend only (uvicorn)"
	@echo "  frontend           Run frontend only (vite)"
	@echo "  dev                Run both via startup.sh"
	@echo "  check-db           Check PostgreSQL/PostGIS/pgRouting"
	@echo "  install-schema     Install/update DB schema (idempotent)"
	@echo "  make-test-graph    Generate deterministic 12x12 test grid (CI/tests)"
	@echo "  smoke-route        Quick routing + closure test"
	@echo "  bench              Benchmark routing (p50/p95, avec/sans fermetures)"
	@echo "  test               Unit tests (sans DB)"
	@echo "  test-integration   Integration tests (RUN_INTEGRATION=1, DB requise)"
	@echo "  docker-up          docker compose up --build"
	@echo "  docker-down        docker compose down -v"
	@echo "  lint               py_compile + frontend lint"

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
	cd frontend && npm install

backend:
	cd backend && .venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev -- --host 0.0.0.0 --port 5173

dev:
	./startup.sh

check-db:
	cd backend && .venv/bin/python manage.py check-db

install-schema:
	cd backend && .venv/bin/python manage.py install-schema

make-test-graph:
	cd backend && .venv/bin/python manage.py make-test-graph

smoke-route:
	cd backend && .venv/bin/python manage.py smoke-route

bench:
	cd backend && .venv/bin/python manage.py bench-route --runs 20 --closures 5

test:
	cd backend && .venv/bin/python -m pytest -q

test-integration:
	cd backend && RUN_INTEGRATION=1 .venv/bin/python -m pytest -q -m integration

docker-up:
	docker compose up --build

docker-down:
	docker compose down -v

lint:
	cd backend && .venv/bin/python -m py_compile app/main.py
	cd frontend && npm run lint || true
