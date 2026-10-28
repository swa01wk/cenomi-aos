# Skill: supplier_lookup

Finds suppliers for the brief's category in the ERP and ranks them with cited sources. **Milestone:** M2.
**Stops:** 5 (runs in parallel), 6 (Noura asks why a supplier ranks second).

## Where it runs

| Run | Created by | On behalf of | Ceiling |
| --- | --- | --- | --- |
| Task `supplier_lookup` in region `discovery` | `event.intent_identified` | buyer | shareable |

The region joins at `shortlisting`; the join guard `same(brief_version)` re-runs this Task if the confirmed brief is
newer than the one it ranked against.

## Contract

- **Inputs:** latest `brief` version. `dependency_versions: {brief_version: n}`.
- **Tools:** `read_artifact`, `save_draft` (supplier_list), `search_suppliers`, `get_supplier_history` (reads, mock ERP).
- **Budget per attempt:** 50,000 tokens · USD 1.20 · 300 s · 10 steps · 10 actions · 2 retries.
- **Output:** `supplier_list` (row-based), cardinality one. **Acceptance:** `sources_cited`.

## Behaviour

- Search the category, fetch history for each match, then score with a fixed rubric: 20 for approved-list presence,
  up to 50 from past POs in the category (5 each), up to 30 from on-time % on those POs (30% of the percentage). Store
  `points_asl`, `points_history`, `points_delivery`, and `score` on each row; the verifier checks the sum.
- No prices: the ERP tools return none, and the ceiling would strip them anyway.
- Every row carries `sources`: the receipt refs of the `search_suppliers` and `get_supplier_history` calls it used.
- "Why is X second?" in an assist turn is answered from the saved `supplier_list` and its sources; the assist
  contract for that turn has no ERP tools, so it cannot fetch new data (board WS-Shortlist: "no new tool calls").

## Verifier `sources_cited` (rule)

PASS when: every row has at least one source; every source ref is a receipt from this Task's own tool calls; each
`supplier_id` appears in a `search_suppliers` receipt; `rank` is 1..n with no gaps and ordered by `score` descending.
REWORK otherwise, naming the rows.

## Kernel rules around it

- On completion the region is `done`. At `shortlisting` the kernel opens *Confirm the shortlist* for the buyer once the
  buyer is bound (claim). The decision's `selection` sets `attr.shortlist_count`; the guard needs ≥ 3.

## Fake model script `happy`

`search_suppliers {category}` → `get_supplier_history` × 5 → `save_draft` supplier_list (5 rows, Najd 88, Al Noor 81,
Desert Clean 77, Gulf Janitorial 64, Riyadh Facility Mart 58) → finish. The script can't know receipt refs in
advance: a source written `{{receipt:TOOL}}` or `{{receipt:TOOL:TEXT}}` is filled in by the fake model with the ref of
the latest TOOL result whose arguments contain TEXT.

## Evals and tests

- Behavioral (M4): never cites a source it didn't fetch; ranks agree with its own scores; abstains (empty list +
  summary) when the category has no suppliers.
- Test: brief edited to v3 after the ranking → join guard fails → a new attempt ranks against v3 before shortlisting
  can proceed (guidebook C09).
