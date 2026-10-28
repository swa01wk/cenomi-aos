# Supplier lookup

Find suppliers for the brief's category in the ERP and rank them with a fixed rubric.

1. Search the ERP with `search_suppliers` for the brief's category id; fetch history with `get_supplier_history` for
   each supplier it returns.
2. For each supplier row, set `past_pos` and `on_time_pct` from `get_supplier_history` (use null for on-time when
   there are no past orders).
3. Score with this rubric only (do not invent other weights):
   - `points_asl`: 20 (they appeared on the approved list for this category).
   - `points_history`: min(`past_pos` × 5, 50).
   - `points_delivery`: round(`on_time_pct` × 0.3) when `past_pos` > 0 and on-time is known; otherwise 0.
   - `score`: the sum of those three point fields.
4. Save one `supplier_list` draft with a row per supplier: rank (1 is best, ordered by `score` descending), supplier,
   supplier_id, email (from `search_suppliers`), past_pos, on_time_pct, points_asl, points_history, points_delivery,
   score, and `sources`.
5. `sources` lists the receipts of the `search_suppliers` and `get_supplier_history` results the row came from. Cite
   only receipts shown in your tool results.
6. Finish with one or two plain sentences: how many suppliers you found, who ranks first, and that the buyer picks the
   shortlist next.
