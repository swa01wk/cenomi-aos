# Quote comparison and purchase order

Compare the captured quotes and, once a supplier is selected, prepare the purchase order.

1. Use `price_calculator` for every total and score. Never do arithmetic yourself.
2. Persist **`pricing_lines`** on each **quote** when the supplier gave a breakdown (device, warranty, delivery, etc.).
3. Save **`quote_line_matrix`** and **`quote_line_scores`** (fair benchmark = median peer price per line) when **two or more** quotes exist.
4. Score = 70% price, 20% lead time, 10% warranty, unless the brief sets other criteria.
5. Save a `comparison` draft ranking **all** quoted suppliers. The buyer selects the supplier; you do not.
   When only **one** quote exists, still save the comparison (one row, score from calculator) in the **first**
   run — do not re-read mail or re-fetch artifacts you already have in `job_snapshot`.
6. After selection, build the `po_payload` for the selected supplier with reference `AOS-<job id>-PR1`, then request `create_pr` (Fusion converts to PO later).
7. If a create outcome is unknown, check with `find_po` by reference before anything else.

## Purchase order — do not loop on questions

When the template is `pr_create` (ordering / requisition stage):

- Read the **brief**, **comparison**, **quote**, and **recent_messages** before calling any tool.
- The buyer already selected a supplier via `decision.supplier_selected`. Do **not** ask which supplier unless no quote and no selection exist in the job records.
- Default **currency SAR** and **ship_to** from the brief `delivery_site` (add city/country from the brief text when needed). Only ask if those fields are literally empty in the brief.
- If the buyer answered currency or address in **recent_messages**, use that answer — do **not** ask again.
- Prefer **`save_draft`** (`po_payload`) and **`request_action`** (`create_pr`) in the same run. Use **`ask_question` at most once** per attempt, only for a field that is missing everywhere above.
- Never repeat the same questions on a resumed attempt after the buyer replied.
