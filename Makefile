.PHONY: help install backend frontend dev check-db install-schema smoke-route docker-up docker-down lint

help:
	@echo "Targets:"
	@echo "  install        Install backend venv + frontend deps"
	@echo "  backend        Run backend only (uvicorn)"
	@echo "  frontend       Run frontend only (vite)"
	@echo "  dev            Run both via startup.sh"
	@echo "  check-db       Check PostgreSQL/PostGIS/pgRouting"
	@echo "  install-schema Install/update DB schema"
	@echo "  smoke-route    Quick routing + closure test"
	@echo "  docker-up      docker compose up --build"
	@echo "  docker-down    docker compose down"

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
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

smoke-route:
	cd backend && .venv/bin/python manage.py smoke-route

docker-up:
	docker compose up --build

docker-down:
	docker compose down -v

lint:
	cd backend && .venv/bin/python -m py_compile app/main.py
	cd frontend && npm run lint || true
