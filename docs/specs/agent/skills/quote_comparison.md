# Skill: quote_comparison

Compares the captured quotes, then prepares and requests the purchase order. **Milestone:** M3. **Stops:** 11, 12, 13.

## Where it runs

| Run | Template | Created by | On behalf of | Ceiling |
| --- | --- | --- | --- | --- |
| Compare | `quote_comparison` (analysis) | entering `comparison` | buyer | restricted |
| Order | `po_create` (record_update) | entering `ordering` | buyer | restricted |

## Contract (compare)

- **Inputs:** brief (final), every captured quote. `dependency_versions: {brief_version, quote_count}`.
- **Tools:** `read_artifact`, `price_calculator` (compute), `save_draft` (comparison).
- **Budget:** 40,000 tokens · USD 1.00 · 300 s · 8 steps · 8 actions · 2 retries.
- **Output:** `comparison` (row-based). **Acceptance:** `score_recompute`.

## Contract (order)

- **Inputs:** comparison (locked), the selection decision, brief.
- **Tools:** `read_artifact`, `save_draft` (po_payload), `request_action(create_po)`.
- **Budget:** 30,000 tokens · USD 0.80 · 300 s · 6 steps · 6 actions · 2 retries.
- **Output:** `po_payload`. **Acceptance:** `payload_match` on the executed action.
- **Policy:** `quick_quote_gates#po_create`: REQUIRE_APPROVAL, chain `participant:buyer` (content) then
  `participant:procurement_approver` on every PO, whatever the amount; segregation `not_requester`,
  `distinct_approvers`; due 1 day.

## Behaviour

- Every total and score comes from `price_calculator`; the model never does arithmetic. Default weights 70% price,
  20% lead time, 10% warranty unless the brief sets others.
- The buyer selects; the agent does not. Selecting raises `decision.supplier_selected` and locks the comparison.
- PO payload: supplier, `ship_to` = brief site, `need_by` = brief delivery date, currency SAR, one line per item,
  `po_amount` = the calculator's total, `reference` = `AOS-<instance>-PO1`.
- If `request_action` reports an unknown outcome, the agent waits; the kernel's reconciler runs `find_po` by reference.
  The agent never retries `create_po` itself.

## Kernel rules around it

- Saving a `po_payload` version sets `attr.po_amount`; the chain length is decided from it when the approval opens.
- After approval and execution, `payload_match` reads the PO back with `find_po` and compares supplier, lines,
  amount, need-by and reference with the approved payload. PASS → `task.completed.po_create` → `closed` with handover,
  Outcome Record and timer cancellation.

## Verifier `score_recompute` (rule)

Recompute every row's total and score with the calculator from the captured quote versions; PASS only when every value
matches exactly and ranks follow scores. Suppliers with no quote appear as "no quote by the deadline", unranked.

## Fake model script `happy`

Compare: `price_calculator` × 2 → `save_draft` comparison (Najd 92.4, SAR 38,400; Al Noor 86.1, SAR 40,400; Desert
Clean no quote) → finish. Order: `save_draft` po_payload (SAR 38,400) → `request_action(create_po)` → interrupt → resume
→ `request_action` → receipt → finish.

## Tests

- Two-step chain at any amount: SAR 38,400 and SAR 18,600 (QQ-0003) both need the buyer, then the procurement
  approver.
- Noura cannot approve step 2; Khalid cannot approve step 1 after approving step 2 (distinct approvers).
- ERP `timeout_after_commit` → UNKNOWN → reconciled → exactly one PO (stop 13, guidebook C04).
- A changed comparison after selection is impossible: the artifact is locked (409).
