# Quote comparison and purchase order

Compare the captured quotes and, once a supplier is selected, prepare the purchase order.

1. Use `price_calculator` for every total and score. Never do arithmetic yourself.
2. Score = 70% price, 20% lead time, 10% warranty, unless the brief sets other criteria.
3. Save a `comparison` draft ranking the quotes. The buyer selects the supplier; you do not.
4. After selection, build the `po_payload` for the selected supplier with reference `AOS-<job id>-PO1`, then request `create_po`.
5. If a create outcome is unknown, check with `find_po` by reference before anything else.
