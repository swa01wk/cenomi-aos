# Client demo — full RFP (Noura, Samir, Rami)

Use this after a clean slate. **Backup** a golden run when it looks good so you can restore if a live demo fails.

## 0. Full demo in one command (recommended for client)

```bash
make demo-client-full    # reset + load **RFP-0001** (web) and **QQ-0001** / **QQ-0013** (iPhone) with full eval + BAFO + Q&A routing

make verify-demo-rfp     # optional: confirm spec stage, rubrics, and chat needles on RFP-0001

make demo-rfp-full       # RFP only (same as client-full RFP half)
```

Then sign in as **Noura**, **Samir (cdo)**, or **Rami** and open **RFP-0001**. No waiting on intake.

The bootstrap includes the full **specification stage** (**RFP validation**, **Template check**, **Scoring agreement**, **RFP uploads**, chat send-back to **Faisal**), **Master RFP** (70/30 QCBS evaluation text), supplier clarifications (commercial → **Noura**, technical → **Rami**), **module-level** pricing, evaluation sheets with **Show scoring rubric**, and **BAFO** — lands on **BAFO negotiation**.

## 0b. Clean slate only (live run from scratch)

```bash
make reset-demo          # wipes jobs, chat, mail; re-seeds org
make sync-pack-docker    # pack v44+ with category manager clarifications
```

Ensure in `.env`:

- `AOS_DEMO=1`
- Worker running with `OPENAI_API_KEY` (real agent turns) **or** accept kernel-posted progress lines during supplier simulation

Open **http://localhost:8080**

## 1. Backup / restore (safety net)

After a successful dry run (job at **Evaluation** or **Closed**):

```bash
make demo-backup INSTANCE=RFP-0001
# writes demo/backups/RFP-0001-<timestamp>.json
```

If the live demo breaks:

```bash
make demo-restore FILE=demo/backups/RFP-0001-....json
# reopen the same job URL; all three personas see their chat history
```

Platform admin token is used by the script (see `scripts/demo-backup.sh`).

## 2. Personas

| Person | Sign-in | Role in this journey |
|--------|---------|----------------------|
| **Noura** | People → Noura | Sourcing buyer — intake, shortlist, invitations, evaluation, award |
| **Samir Al-Farsi** | People → Samir (`cdo`) | CDO — master RFP approval before any vendor email |
| **Rami Al-Otaibi** | People → Rami | Category manager — technical clarifications, dual evaluation review, vendor recommendation |

## 3. Start the job (Noura)

**People → Sourcing specialist** (Noura). Paste from [rfp-start-prompt.md](./rfp-start-prompt.md).

Watch for **`RFP-0001`** (not QQ-). Chat with the agent until intake completes; brief auto-confirms for sourcing starters.

## 4. Noura — shortlist and send

1. Confirm shortlist (≥3 IT vendors).
2. In **Documents**, review **RFP validation**, **Template check**, **Scoring agreement**, **RFP uploads**, then **Master RFP** (or use **demo-client-full** to skip live intake).
3. **Sign out → Samir** (step 5). Return as Noura after CDO approval.

## 5. Samir — master RFP (CDO)

1. **Team queue** (not empty home) → open the RFP job.
2. **Documents → Master RFP** — edit in panel if you want a visible CDO touch.
3. Confirm **Review and approve master RFP** in the thread.
4. Sign out → **Noura**.

## 6. Noura — invitations

1. **Drafts** tab — three **Invite · …** emails.
2. **Approve and send** (dock at bottom).
3. State **Awaiting proposals**.

## 7. Supplier simulation (automatic)

With `AOS_DEMO=1`, per vendor (~2–4 min each, staggered):

1. **Ack** — appears under **Responses → RFP responses**
2. **Three clarification questions** — tagged **commercial** or **technical**; draft answers in proposal **Notes**
3. **Noura** gets commercial **Send commercial clarification …**; **Rami** gets technical **Send technical clarification …**
4. **Full proposal** with mock SAR totals
5. Agent posts short progress lines in the thread for the client

Optional: `POST /api/demo/clock/advance` `{ "to_next_timer": true }` as platform admin to move to **Evaluation** after proposals.

## 8. Clarifications (Noura and Rami)

1. **Noura** — commercial cards only: open **Responses**, read the question + draft in **Notes**, confirm **Send commercial clarification**.
2. **Rami** — technical cards only: same flow with **Send technical clarification**; edit the draft in **Notes** if needed before approve.
3. Each approval posts the answer in the thread; commercial questions never appear on Rami’s queue.

## 9. Noura — BAFO (module pricing)

1. Bootstrap opens at **BAFO negotiation** with **Module comparison** and **Module scores** (fair benchmark vs each vendor per scope module).
2. **Drafts → BAFO · …** — each email asks why the vendor charged X for a module when peer submissions suggest ~Y.
3. Approve **Send BAFO to …** in the thread for each outlier vendor, then **Complete BAFO round** (refreshes scores from demo BAFO responses).

## 10. Rami — recommendation

1. After BAFO, the job returns to **Evaluation**.
2. Work panel: **Commercial eval**, **Technical eval**, **Weighted eval**.
3. **Recommend vendor for award** — pick a row or note a different preference.
4. **Noura** continues **Requisition** → Fusion PR → **Closed**.

## 11. What to show the client

- **Three different inboxes/queues** with real decision cards and thread history.
- **Work panel**: **Drafts / Responses / Documents** instead of a long tab strip.
- **RFP responses** table: ack → each vendor clarification email (with draft CM answer) → full proposal per supplier. On a **Reply · …** tab, use the version dropdown (v1–v5) to step through the same history.
- **Backup JSON** on your laptop if you need to rewind mid-presentation.

## Timing cheat sheet (default demo env)

| Event | ~When |
|-------|--------|
| First ack | +20s after send |
| Next vendor acks | +25s stagger |
| Each clarification | +28s |
| Full proposal after Q3 | +35s |
| Quote/proposal deadline timer | 90s demo window |

Adjust via `AOS_DEMO_RFP_*` in `.env.example`.
