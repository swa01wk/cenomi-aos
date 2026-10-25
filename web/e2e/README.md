# Playwright end-to-end tests

Most specs run against a stack started with `make up` (Postgres, API, nginx serving the built web app).

## Sign-in and routing

`sign-in-routing.spec.ts` is safe on a long-lived database: it only exercises auth and navigation.

## Walkthrough stops (stateful)

Stops **1–5** change kernel state (publish, Seat lifecycle, job start, chat). They assume a **fresh** database and a **worker** using `AOS_RUNTIME=fake` (intake runs the `request_intake.happy` Task script by skill name):

```bash
make down V=1 && make up      # make up mints AOS_WORKER_TOKEN into .env if missing
cd web && npm run e2e
```

`make up` runs `scripts/dev-worker-token.sh --if-missing`, which writes a worker token to `.env`.
`make worker-token` mints a new one, e.g. after changing `AOS_SESSION_SECRET`.

Playwright runs stop projects in order (`dependencies`, serial mode, no retries). Do not run these projects in parallel with each other or against a dirty stack.

Later milestones add more stop specs; M5 runs the full chain twice on a clean stack.
