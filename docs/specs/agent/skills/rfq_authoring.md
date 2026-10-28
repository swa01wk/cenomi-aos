# Skill: rfq_authoring

Drafts one request for quotation per shortlisted supplier, then asks to send them. **Milestone:** M2 (drafting and
REWORK), M3 (sending with approval). **Stops:** 7, 8.

## Where it runs

| Run | Template | Created by | On behalf of | Ceiling |
| --- | --- | --- | --- | --- |
| Draft | `rfq_draft` (document_draft) | entering `rfq_drafting` | buyer | **shareable** |
| Send | `rfq_send` (outbound_communication) | entering `rfq_sending` | buyer | shareable |

The shareable ceiling means `budget_guidance` (internal) is **not in the context at all**. `leak_check` is the second
line of defence; the demo's `seed_budget_leak` switch makes the fake model leak anyway so the REWORK path is shown.

## Contract (draft)

- **Inputs:** brief (final), supplier_list, shortlist decision. `dependency_versions: {brief_version, shortlist_count}`.
- **Tools:** `read_artifact`, `save_draft` (rfq_email, key = supplier_id), `leak_check_diff` (compute),
  `draft_message` (staged write, mock mail), `ask_question`.
- **Budget:** 60,000 tokens · USD 1.50 · 600 s · 12 steps · 10 actions · 2 retries.
- **Output:** `rfq_email` per shortlisted supplier. **Acceptance:** `leak_check`.

## Contract (send)

- **Inputs:** the rfq_email versions that passed `leak_check`.
- **Tools:** `read_artifact`, `request_action(send_message)`.
- **Budget:** 20,000 tokens · USD 0.50 · 300 s · 6 steps · 10 actions · 2 retries.
- **Output:** none (`cardinality: none`). **Acceptance:** `recipient_check` on the action receipts.
- **Policy:** `quick_quote_gates#rfq_send`: REQUIRE_APPROVAL by `participant:buyer`, condition
  `artifact.verification.leak_check == "PASS"`, due 1 day.

## Send flow (M3)

1. The graph builds one `request_action(send_message)` per email, all in one approval request
   (`artifact_refs` = the 3 email versions). Kernel: REQUIRE_APPROVAL, approval bound to the 3 digests.
2. `interrupt()` → `/checkpoint` → attempt ends `waiting_approval`.
3. Noura edits one email → v3 → the open approval is **voided**; the Task is READY again. The resumed attempt goes
   straight to `request_action` with the latest versions (no model step) → new approval → Noura approves.
4. Resume on a new attempt → `request_action` again → ALLOW → the gateway sends each with key
   `<instance>:rfq_send:<supplier_id>` → receipts. Kernel starts `quote_deadline` on `task.completed.rfq_send`.

## Verifiers

`leak_check` (rule) — PASS when no value of any `internal` or `restricted` field of any artifact in the instance
appears in any shareable output field. Matching normalises numbers (strip currency words and symbols, thousands
separators and spaces; `40,000`, `SAR 40000` and `40k` all match 40000) and is case-insensitive for text. Match
numbers as whole values (140000 does not match 40000) and text as whole phrases. Ignore text values under 4
characters and numbers under 3 digits (too common to count as a leak). REWORK with the output field and the source
field name (never the value itself) as the finding.

`recipient_check` (rule) — for each send receipt, `find_message` returns the message with `to` equal to the supplier's
ERP email, the instance's `conversation_id`, and the body hash of the approved version.

## Fake model scripts

`happy`: per supplier `save_draft` + `leak_check_diff` + `draft_message`; finish. `leak`: the first draft's body
includes the brief's budget figure from the script (the script has it; the envelope doesn't) → `leak_check` REWORK →
attempt 2 runs `happy`.

The scripts are named for the template (`rfq_draft.happy`, `rfq_draft.leak`), since `rfq_send` runs the same Skill.
In M2 they only `save_draft` (key = supplier_id) and finish: `leak_check_diff` needs the gateway's builtin
tool transport and `draft_message` needs the job's mailbox conversation (both M3). Until the `seed_budget_leak`
switch exists (M3), the worker runs `leak` when `AOS_FAKE_SCENARIO=leak`.

## Evals and tests

- Behavioral (M4): emails contain item, quantity, specification, delivery date and site, reply deadline; nothing else
  from the brief; one email per shortlisted supplier.
- Tests: REWORK then PASS (stop 7); editing after approval voids it (guidebook C05 adapted); send timeout after commit
  → reconciled by `find_message`, exactly one message per supplier; resume re-checks policy (a kill switch between
  approval and resume blocks the send).
