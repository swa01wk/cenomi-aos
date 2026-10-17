# ADR 013 — Streamed UI: snapshot, cursor and typed blocks

- **Status:** Proposed
- **Owner:** Frontend lead

## Decision
- Pages load an authoritative snapshot, then follow an SSE stream of `UiEvent`s from the snapshot's cursor. Unknown
  cursor or gap → `snapshot.required` → reload (guidebook C10).
- The outbox table in Postgres is the stream's source; `LISTEN/NOTIFY` wakes the hub. No Redis.
- Agent output reaches the UI as text deltas and typed blocks rendered by fixed components. No model-written HTML or
  Markdown is ever rendered as markup.
- Commands carry what the person saw (`expected_version`, `payload_hash`); conflicts are shown, never auto-retried.

## Alternatives
WebSockets (no benefit for one-way streams here); AG-UI (compatible later: the event types map onto it).

## Verification
Reconnect test rebuilds the job page from snapshot + cursor with no duplicate turns; a stale decision shows
`ConflictNotice`.
