# Supplier lookup

Find suppliers for the brief's category in the ERP and rank them.

1. Search the ERP with `search_suppliers` for the brief's category id; fetch history with `get_supplier_history` for
   each supplier it returns.
2. Score each supplier on category match, past orders and on-time delivery. Do not use prices; none are available here.
3. Save one `supplier_list` draft with a row per supplier: rank (1 is best, ordered by score), supplier, supplier_id,
   email (from `search_suppliers`), past_pos, on_time_pct, score and `sources`.
4. `sources` lists the receipts of the `search_suppliers` and `get_supplier_history` results the row came from. Cite
   only receipts shown in your tool results.
5. Finish with one or two plain sentences: how many suppliers you found, who ranks first, and that the buyer picks the
   shortlist next.
