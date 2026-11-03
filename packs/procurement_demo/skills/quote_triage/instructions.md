# Quote triage

A supplier replied on an RFQ thread. Capture their quote.

1. Read the thread with `read_thread`, using the **exact** `conversation_id` from `trigger_context` in the context envelope (never guess a id like "job").
2. Use **every** supplier inbox message on that thread, oldest first. Later messages often complete missing fields or **correct** earlier ones (price, total, lead time, delivery date). For each field, prefer the **newest** non-empty value you find across the thread.
3. When a message ends with a block headed `Quote fields (auto-detected from email)`, treat those numbers as authoritative (they were parsed from the email body). Still set `reply_excerpt` from the supplier’s own wording above that block.
4. Extract unit price, total for the requested quantity, lead time and warranty. Use **numeric** amounts (not strings with “SAR”). If still missing after reading the full thread, record it as missing; never guess.
5. Save a `quote` draft keyed by `trigger_context.party_id`. If a quote for that key already exists in the job snapshot, save a **new version** (`artifact_id` + `base_version` from the snapshot) with merged/corrected values — do not create a second quote for the same supplier.
6. Set `reply_excerpt` from the **latest** supplier message that contains pricing (or the triggering message if it is the only one). In `notes`, briefly say when a follow-up or correction email changed anything (e.g. "Second email updated unit price from … to …").
7. If they ask for more time or a deadline extension, say so in the quote notes field; still capture any prices they gave.
