# Quote triage

A supplier replied on an RFQ thread. Capture their quote.

1. Read the thread with `read_thread`, using the **exact** `conversation_id` from `trigger_context` in the context envelope (never guess a id like "job").
2. Extract unit price, total for the requested quantity, lead time and warranty. If something is missing, record it as missing; never guess.
3. Save a `quote` draft keyed by `trigger_context.supplier_id`. Include a short `reply_excerpt` (the supplier's reply text, trimmed) and any buyer-facing `notes`.
4. If they ask for more time or a deadline extension, say so in the quote notes field; still capture any prices they gave.
