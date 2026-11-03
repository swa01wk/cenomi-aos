# Proposal triage

A supplier replied on an RFP thread. Capture their **proposal** (same rules as quote triage).

1. Read the thread with `read_thread` using `trigger_context.conversation_id` from the envelope.
2. Use every supplier inbox message, oldest first; prefer the newest non-empty value per field.
3. When a message includes `Quote fields (auto-detected from email)`, treat those numbers as authoritative. Use numeric amounts, not strings with currency symbols.
4. Save a `proposal` draft keyed by `trigger_context.party_id`. Merge into a new version if one already exists for that supplier.
5. Set `reply_excerpt` from the latest message with pricing. Never guess missing unit price or total.
