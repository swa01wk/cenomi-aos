# RFP evaluation and purchase order

Compare captured **proposals** and, after award, raise the purchase order.

1. Use `price_calculator` for every total and score. Never do arithmetic yourself.
2. Save `rfp_evaluation` with ranked rows from the proposals (same scoring approach as quote comparison).
3. After the buyer selects a supplier, build `po_payload` and request `create_po` when the template is `rfp_po_create`.
4. Prefer finishing PO draft and create in one run; ask at most one clarifying question if a required field is missing everywhere in the job snapshot.
