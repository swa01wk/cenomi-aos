# ADR 014 — Model provider behind the alias: OpenAI for development

- **Status:** Proposed
- **Owner:** Runtime lead

## Context
Skills ask for a model alias (`enterprise_reasoning`), not a provider (reference architecture v1.2 ADR-07). The specs
first mapped the alias to Claude. The team develops with an OpenAI key and wants `gpt-5.4-mini` for day-to-day work:
it's cheaper and faster for the many real-model runs during M1–M4.

## Decision
- The alias registry (`worker/models.py`) chooses the provider from `AOS_MODEL_PROVIDER`: `openai` (default) or
  `anthropic`. The model id comes from `OPENAI_MODEL` (development: `gpt-5.4-mini`) or `ANTHROPIC_MODEL`, with an
  optional per-alias override `AOS_MODEL_ENTERPRISE_REASONING=provider:model`.
- Graphs and tool schemas are provider-neutral: LangChain chat models with `bind_tools`, plain JSON Schema tools.
  Switching provider is a configuration change and needs no code change.
- `temperature` is passed only when `AOS_MODEL_TEMPERATURE` is set, because some reasoning models accept only their
  default.
- Prices per million tokens come from configuration (`AOS_MODEL_PRICE_IN_PER_MTOK`, `AOS_MODEL_PRICE_OUT_PER_MTOK`).
  They are never hard-coded. A real-model run without them is refused, because the daily USD limit couldn't be
  enforced.
- No fallback between providers in the POC; a provider error retries once on a new attempt, then stops safely.
- Tests and CI use the fake model only and need no key.

## Consequences
- The demo data that reaches the model (QQ-0001, mock suppliers) is synthetic; the provider's data terms apply to it.
  Real company data needs a review before any real-model run.
- Model quality is a measured question: the M4 behavioral evals and the M5 baseline ADR record the pass rates for the
  model actually used. If `gpt-5.4-mini` misses an eval threshold on a Skill, the fix is a per-alias override to a
  larger model, not a code change.

## Alternatives
- Claude only (the original spec): kept as the `anthropic` option.
- Calling provider SDKs directly instead of LangChain chat models: more code per provider and no shared tool-calling
  interface.

## Verification
Unit tests resolve the alias for both providers and the override, omit `temperature` when unset, and compute cost
from the configured prices. A manual smoke test (`AOS_REAL_MODEL=1`) runs one `request_intake` turn on the configured
model.
