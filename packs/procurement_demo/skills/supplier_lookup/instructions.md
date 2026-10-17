# Supplier lookup

Find suppliers for the brief's category in the ERP and rank them.

1. Search the ERP with `search_suppliers` for the brief's category; fetch history with `get_supplier_history`.
2. Score each supplier on category match, past orders and on-time delivery. Do not use prices; none are available here.
3. Every score must cite the ERP records it came from in `sources`.
4. Save the ranking as a `supplier_list` draft tied to the current brief version.
