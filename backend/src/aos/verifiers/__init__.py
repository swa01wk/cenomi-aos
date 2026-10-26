"""Rule verifiers a pack points to by `implementation: aos.verifiers.<module>` (pack extensions).

Each module has pure `check_*` functions (unit-tested from the Skill specs) and an async
`verify(conn, gate, result, defs) -> (verdict, findings)` that `kernel/verify.py` runs on submit.
Findings are plain sentences for the model's next attempt and the Console; they never quote a protected value.
"""
