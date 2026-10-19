# Playwright end-to-end tests

Most specs run against a stack started with `make up` (Postgres, API, nginx serving the built web app).

## Sign-in and routing

`sign-in-routing.spec.ts` is safe on a long-lived database: it only exercises auth and navigation.

## Walkthrough stops (stateful)

Stops **1–3** change kernel state (publish, Seat lifecycle). They assume a **fresh** database:

```bash
make down V=1 && make up
cd web && npm run e2e -- --project=stop-01 --project=stop-02 --project=stop-03
```

Playwright runs `stop-01`, then `stop-02`, then `stop-03` in order (`dependencies`, serial mode, no retries). Do not run these projects in parallel with each other or against a dirty stack.

Later milestones add more stop specs; M5 runs the full chain twice on a clean stack.
