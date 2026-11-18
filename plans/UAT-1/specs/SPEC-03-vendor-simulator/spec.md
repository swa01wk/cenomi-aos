# SPEC-03: Vendor simulator replies by mail only

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: backend
Owner: Saad | Planned: 1 · Tue 17 Nov | Estimate: 1 ed (engineer-days)
Requirements: R-QQ-07, R-RFP-08, R-RFP-15 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-03-vendor-simulator` | Depends on: SPEC-02

## Goal

Simulated vendors behave like real ones: they send email to the job's threads, and the agent has to read it.

## Scope

In:
- Rework `kernel/demo_rfp_acks.py` into `connectors/vendor_sim.py` (pack-neutral name, allowlisted data): a scheduler tick, gated by `AOS_VENDOR_SIM`, that sends mail through `connectors/demo_replies.simulate_vendor_reply_on_thread` only. It never writes artifacts, attributes or turns.
- Timeline per invited vendor (same env knobs `AOS_DEMO_RFP_*`): RFP ack -> the three questions from `demo_clarification_bank` -> proposal with module pricing (`demo_proposal_pricing_modules`) as an email body plus attachment-style text block; QQ: one quote email per RFQ (amounts from `demo_qq_lines`).
- BAFO: when a `bafo_email` is sent to a vendor, reply with revised module prices (`demo_proposal_pricing_modules(post_bafo=True)`).
- One scenario per run is an injection email (instruction text inside the body) so CI exercises C06.
- Remove the call from `GET /instances/{id}` (SPEC-01) and from `kernel/scheduler.py` demo tick; register the new tick when `vendor_sim` is on.

Out:
- Parsing the mail (SPEC-05, SPEC-14).

## Design

Mail flows mock_mail -> `AOS_INBOUND_URL` webhook -> `kernel/inbound_mail.record_inbound_message` -> `mail.message_received` event -> triage task. Idempotency: one `(thread, step)` marker per sent simulator message in `work.instances.attributes.vendor_sim` so restarts never resend.

## Acceptance criteria

- AC1: Given three invited RFP vendors and `AOS_VENDOR_SIM=1`, when the timeline runs, then each thread receives ack, three questions and one proposal by mail, and no artifact is written by the simulator.
- AC2: Given a sent RFQ, when the timeline runs, then one quote email arrives on that thread.
- AC3: Given a sent BAFO email, when the simulator ticks, then the vendor replies once with revised prices.
- AC4: Given the API restarts mid-timeline, when the tick resumes, then no message is sent twice.

## Tests

- T-03-1 unit: Timeline builder: order, stagger, idempotency markers.
- T-03-2 integration: Stack test: send RFQ -> simulator mail lands in mock_mail -> inbound row recorded.
- T-03-3 unit: Injection scenario body is produced once per run.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Log `vendor_sim.sent` with instance, supplier, step.

## Files likely touched

- `backend/src/aos/kernel/demo_rfp_acks.py`
- `backend/src/aos/connectors/`
- `backend/src/aos/kernel/scheduler.py`
- `backend/tests/`

## Dependencies

SPEC-02
