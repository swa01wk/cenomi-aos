# AOS POC — common tasks. Run from the repo root.
# Settings in .env (copy .env.example) are loaded here and passed to Docker Compose.
ifneq (,$(wildcard .env))
include .env
export
endif
PY        ?= python3
PYPATH    := src:.vendor
COMPOSE   := docker compose $(if $(wildcard .env),--env-file .env,) -f deploy/docker-compose.yml
PACK      ?= packs/procurement_demo
ORG       ?= seed/org.yaml

.PHONY: help install vendor test validate check db up down logs ps dev-api dev-web web-offline clean

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: ## install backend (editable, with dev tools) and web dependencies
	$(PY) -m pip install -e 'backend[dev,runtime]'
	cd web && npm ci

web-test: ## run Vitest in web/
	cd web && npm test

vendor: ## sandbox fallback: fetch FastAPI and psycopg from GitHub when PyPI is blocked
	bash scripts/vendor-from-github.sh

test: ## run all backend tests (Postgres tests skip if no local Postgres)
	cd backend && PYTHONPATH=$(PYPATH) $(PY) -m unittest discover -s tests -t . -v

validate: ## aos validate the demo pack against the seeded organization
	cd backend && PYTHONPATH=$(PYPATH) $(PY) -m aos.cli validate ../$(PACK) --org ../$(ORG)

check: test validate ## everything a story must keep green before it is done

db: ## start only Postgres (for make test and make dev-api on a laptop)
	$(COMPOSE) up -d --wait postgres

up: ## build and start the M0 stack; waits until every service is healthy
	$(COMPOSE) up -d --build --wait
	@echo "Web http://localhost:8080 · API http://localhost:8000/docs · mock ERP :8101 · mock mail :8102"

down: ## stop the stack (keeps data; add V=1 to drop volumes)
	$(COMPOSE) down $(if $(V),-v,)

logs: ## follow logs
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

dev-api: ## kernel API with reload against AOS_DATABASE_URL (default: local Postgres, db aos)
	cd backend && PYTHONPATH=$(PYPATH) $(PY) -m uvicorn aos.api.main:app --reload --port 8000

dev-web: ## Vite dev server on :5173, proxying /api to :8000
	cd web && npm run dev

web-offline: ## build web/dist with esbuild only (NODE_MODULES=path with react, react-dom, esbuild)
	cd web && node scripts/build-offline.mjs

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf web/dist
