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

.PHONY: help install vendor test validate api-types check smoke-real model-real model-fake gate diag db up compose-up worker-token down logs ps dev-api dev-web web-offline e2e clean

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
	@# Real-model settings in .env never reach the tests (make smoke-real is the real-model target).
	cd backend && env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u AOS_MODEL_PRICE_IN_PER_MTOK \
		-u AOS_MODEL_PRICE_OUT_PER_MTOK PYTHONPATH=$(PYPATH) $(PY) -m unittest discover -s tests -t . -v

validate: ## aos validate the demo pack against the seeded organization
	cd backend && PYTHONPATH=$(PYPATH) $(PY) -m aos.cli validate ../$(PACK) --org ../$(ORG)

sync-pack: ## sync on-disk pack into Postgres, publish it, and repoint seats (after pack.yaml version bumps)
	bash scripts/sync-pack.sh

api-types: ## regenerate the web API types from openapi.yaml; fails if the committed file is out of date (as CI does)
	cd web && npm run --silent gen:api && git diff --exit-code -- src/api/schema.d.ts

check: test validate api-types ## everything a story must keep green before it is done

model-real: ## switch the Compose worker to the real model (asks only for a missing key; MODEL= PRICE_IN= PRICE_OUT= override)
	@bash scripts/dev-model.sh real

model-fake: ## switch the Compose worker back to the scripted model
	@bash scripts/dev-model.sh fake

gate: ## M1 exit gate on the real model: fresh stack, stops 1-3, Faisal's chat checked; RUNS=3 repeats the chat
	@bash scripts/gate.sh $(or $(RUNS),1)

smoke-real: ## real-model smoke tests (needs OPENAI_API_KEY, OPENAI_MODEL and both prices in .env, and `make db`)
	cd backend && AOS_REAL_MODEL=1 PYTHONPATH=$(PYPATH) $(PY) -m unittest -v \
		tests.test_worker_models.RealModelSmokeTests tests.test_request_intake_assist.RequestIntakeRealModelSmoke

db: ## start only Postgres (for make test and make dev-api on a laptop)
	@# Postgres doesn't need the worker token, but Compose interpolates the whole file.
	AOS_WORKER_TOKEN=$${AOS_WORKER_TOKEN:-unused} $(COMPOSE) up -d --wait postgres

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

diag: ## why didn't the worker reply? worker log, then the latest model calls, tool requests and failures
	$(COMPOSE) logs worker --tail=150
	@$(COMPOSE) exec -T postgres psql -U aos_owner -d aos -c "select event_type, \
		coalesce(attributes->>'tool', attributes->>'failure_category', attributes->>'model') as detail, redacted_summary \
		from evidence.execution_events where event_type in ('TaskFailed','ModelInvoked','ToolRequested','ToolDenied', \
		'ToolCompleted','ArtifactProduced') order by occurred_at desc, aggregate_seq desc limit 16"
	@$(COMPOSE) exec -T postgres psql -U aos_owner -d aos -c "select o->>'tool' as tool, o->'args' as args, \
		left((o->'content')::text, 160) as result from work.attempts a, jsonb_array_elements(a.tool_observations) o \
		where a.id = (select id from work.attempts where jsonb_array_length(coalesce(tool_observations, '[]'::jsonb)) > 0 \
		order by admitted_at desc limit 1)"

dev-api: ## kernel API with reload against AOS_DATABASE_URL (default: local Postgres, db aos)
	cd backend && PYTHONPATH=$(PYPATH) $(PY) -m uvicorn aos.api.main:app --reload --port 8000

dev-web: ## Vite dev server on :5173, proxying /api to :8000
	cd web && npm run dev

web-offline: ## build web/dist with esbuild only (NODE_MODULES=path with react, react-dom, esbuild)
	cd web && node scripts/build-offline.mjs

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf web/dist
