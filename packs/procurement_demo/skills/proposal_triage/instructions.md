# Proposal triage

A supplier replied on an RFP thread. Capture their reply as a `proposal` draft (same supplier key as quote triage).

1. Read the thread with `read_thread` using `trigger_context.conversation_id` from the envelope.
2. Use every supplier inbox message, oldest first; prefer the newest non-empty value per field.
3. Set **`reply_kind`**: `ack` when they confirm receipt or intend to bid without full commercials yet; `question` when they ask clarifications; `proposal` when pricing or a full bid is present.
4. When **`reply_kind`** is `question`, set **`question_lane`**: `commercial` for payment terms, pricing mechanics, SLAs, contract or procurement process; `technical` for architecture, CMS, API, security, hosting, integrations, or delivery approach. Procurement (buyer) handles commercial; category manager handles technical.
5. Set **`acknowledged`** to true when `reply_kind` is `ack`.
6. For `ack` or `question`, you may set `unit_price` and `total` to 0 and `lead_time_days` to 0; always set `reply_excerpt`.
7. For `proposal`, use auto-detected quote fields when present; never guess missing unit price or total.
8. Save keyed by `trigger_context.party_id`. Merge into a new version if one already exists for that supplier.
