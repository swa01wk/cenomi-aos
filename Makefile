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

.PHONY: help install vendor test validate check smoke-real model-real model-fake gate db up compose-up worker-token down logs ps dev-api dev-web web-offline e2e clean

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: ## install backend (editable, with dev tools) and web dependencies
	$(PY) -m pip install -e 'backend[dev,runtime]'
	cd web && npm ci

web-test: ## run Vitest in web/
	cd web && npm test

e2e: ## Playwright sign-in and routing (expects `make up`)
	cd web && npm run e2e

vendor: ## sandbox fallback: fetch FastAPI and psycopg from GitHub when PyPI is blocked
	bash scripts/vendor-from-github.sh

test: ## run all backend tests (Postgres tests skip if no local Postgres)
	cd backend && PYTHONPATH=$(PYPATH) $(PY) -m unittest discover -s tests -t . -v

validate: ## aos validate the demo pack against the seeded organization
	cd backend && PYTHONPATH=$(PYPATH) $(PY) -m aos.cli validate ../$(PACK) --org ../$(ORG)

check: test validate ## everything a story must keep green before it is done

model-real: ## switch the Compose worker to the real model (asks for the key, model and prices when missing)
	@bash scripts/dev-model.sh real

model-fake: ## switch the Compose worker back to the scripted model
	@bash scripts/dev-model.sh fake

gate: ## M1 exit gate setup: real model, fresh stack, publish and activate the Seat (e2e stops 1-3)
	@bash scripts/dev-model.sh real
	@$(MAKE) --no-print-directory down V=1
	@$(MAKE) --no-print-directory up
	cd web && npm run e2e -- --project=stop-01 --project=stop-02 --project=stop-03
	@echo ""
	@echo "Seat active on the real model. Now, at http://localhost:8080 as Faisal: New job -> Quick Quote,"
	@echo "describe a need, answer the agent's questions; expect streamed replies and brief v1 then v2."
	@echo "Worker log: docker compose -f deploy/docker-compose.yml logs -f worker. Back to scripted: make model-fake && make up"

smoke-real: ## real-model smoke tests (needs OPENAI_API_KEY, OPENAI_MODEL and both prices in .env, and `make db`)
	cd backend && AOS_REAL_MODEL=1 PYTHONPATH=$(PYPATH) $(PY) -m unittest -v \
		tests.test_worker_models.RealModelSmokeTests tests.test_request_intake_assist.RequestIntakeRealModelSmoke

db: ## start only Postgres (for make test and make dev-api on a laptop)
	$(COMPOSE) up -d --wait postgres

up: ## build and start the stack (mints a worker token into .env if missing); waits until healthy
	@bash scripts/dev-worker-token.sh --if-missing
	@# A fresh make reads the .env the script may just have written.
	@$(MAKE) --no-print-directory compose-up

compose-up:
	$(COMPOSE) up -d --build --wait
	@echo "Web http://localhost:8080 · API http://localhost:8000/docs · mock ERP :8101 · mock mail :8102"

worker-token: ## mint a new development worker token into .env (AOS_WORKER_TOKEN)
	@bash scripts/dev-worker-token.sh

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
