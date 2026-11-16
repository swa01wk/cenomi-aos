# BAFO negotiation (module-level)

After commercial evaluation, procurement runs a **best-and-final offer** round using **module-level** prices.

1. Read all final **proposal** artifacts with **`pricing_modules`**.
2. Save **`rfp_module_matrix`**: one row per scope module with fair benchmark (median of peer quotes), each vendor column, and a **`bafo_talking_point`** for outliers.
3. Save **`rfp_module_scores`**: one row per module × supplier with **`variance_pct`** and **`module_score`** vs the fair benchmark.
4. For each supplier with material outliers, save a **`bafo_email`** draft (`message_composer`) that asks why they charged X for a module when fair reference is Y, citing peer submissions without naming confidential totals where policy restricts.
5. Do not recommend a vendor until **`decision.bafo_round_complete`** and the category manager resolves **`decision.vendor_recommended`**.
