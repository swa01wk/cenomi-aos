# RFP evaluation and requisition

Compare captured **proposals** in two passes, then combined weighted ranking. After the category manager picks a vendor, raise the purchase requisition.

1. Use `price_calculator` for commercial totals. Never do arithmetic yourself.
2. On each **proposal**, persist **`pricing_modules`** (module_id, name, amount) when the supplier provided a breakdown; otherwise derive modules from the master RFP scope.
3. Save **`rfp_module_matrix`** and **`rfp_module_scores`** before aggregate commercial ranks (fair benchmark = median peer price per module).
4. Save **`rfp_eval_commercial`** with ranked rows (commercial_score from price, delivery, warranty, and module-level variance).
5. Save **`rfp_eval_technical`** with ranked rows (technical_score from scope fit, architecture, compliance — your assessment).
6. Save **`rfp_evaluation`** with the same suppliers: `commercial_score`, `technical_score`, and **`weighted_score`** using weights **0.30 commercial / 0.70 technical** (PRD default; store weights on each row). Save **`technical_criterion_scores`** and **`commercial_criterion_scores`** with 0–5 rubric rows. Save **`eval_scoring_policy`** with formulas.
7. Stop after evaluation until the buyer confirms **`decision.commercial_eval_confirmed`** and the BAFO round completes; the category manager resolves **`decision.vendor_recommended`** only after BAFO.
8. After vendor recommendation, build `po_payload` and request `create_pr` when the template is `rfp_pr_create`.
