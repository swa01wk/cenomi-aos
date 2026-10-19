# Playwright end-to-end tests

Most specs run against a stack started with `make up` (Postgres, API, nginx serving the built web app).

## Sign-in and routing

`sign-in-routing.spec.ts` is safe on a long-lived database: it only exercises auth and navigation.

## Walkthrough stops (stateful)

Stops **1–5** change kernel state (publish, Seat lifecycle, job start, chat). They assume a **fresh** database and a **worker** with the intake fake script:

```bash
# In repo-root .env (loaded by make):
AOS_WORKER_TOKEN=<from: docker compose -f deploy/docker-compose.yml run --rm --no-deps api aos worker-token --worker-id e2e-worker>
AOS_FAKE_SCRIPT=request_intake.happy.yaml

make down V=1 && make up
cd web && npm run e2e -- --project=stop-01 --project=stop-02 --project=stop-03 --project=stop-04 --project=stop-05
```

Playwright runs stop projects in order (`dependencies`, serial mode, no retries). Do not run these projects in parallel with each other or against a dirty stack.

Later milestones add more stop specs; M5 runs the full chain twice on a clean stack.
