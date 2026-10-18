"""Model alias registry (M1-AG-02)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from aos.worker.models import (
    ModelRegistryConfig,
    build_chat_model,
    compute_cost_usd,
    load_model_registry_config,
    resolve_alias,
    validate_real_model_startup,
)


class ModelRegistryTests(unittest.TestCase):
    def test_resolve_openai_default(self) -> None:
        cfg = ModelRegistryConfig(
            provider="openai",
            openai_api_key="k",
            openai_model="gpt-test",
            anthropic_api_key="",
            anthropic_model="",
            enterprise_reasoning_override="",
            temperature="",
            price_in_per_mtok="1",
            price_out_per_mtok="2",
        )
        r = resolve_alias("enterprise_reasoning", cfg)
        self.assertEqual(r.provider, "openai")
        self.assertEqual(r.model_id, "gpt-test")

    def test_resolve_anthropic(self) -> None:
        cfg = ModelRegistryConfig(
            provider="anthropic",
            openai_api_key="",
            openai_model="",
            anthropic_api_key="ak",
            anthropic_model="claude-test",
            enterprise_reasoning_override="",
            temperature="",
            price_in_per_mtok="1",
            price_out_per_mtok="1",
        )
        r = resolve_alias("enterprise_reasoning", cfg)
        self.assertEqual(r.provider, "anthropic")
        self.assertEqual(r.model_id, "claude-test")

    def test_override_wins(self) -> None:
        cfg = ModelRegistryConfig(
            provider="openai",
            openai_api_key="k",
            openai_model="gpt-test",
            anthropic_api_key="",
            anthropic_model="",
            enterprise_reasoning_override="anthropic:claude-override",
            temperature="",
            price_in_per_mtok="1",
            price_out_per_mtok="1",
        )
        r = resolve_alias("enterprise_reasoning", cfg)
        self.assertEqual(r.provider, "anthropic")
        self.assertEqual(r.model_id, "claude-override")

    def test_temperature_omitted_when_unset(self) -> None:
        cfg = ModelRegistryConfig(
            provider="openai",
            openai_api_key="k",
            openai_model="gpt-test",
            anthropic_api_key="",
            anthropic_model="",
            enterprise_reasoning_override="",
            temperature="",
            price_in_per_mtok="1",
            price_out_per_mtok="1",
        )
        resolved = resolve_alias("enterprise_reasoning", cfg)
        with mock.patch("langchain_openai.ChatOpenAI") as ctor:
            build_chat_model(resolved, {"model": {"max_output_tokens": 100}}, cfg)
            kwargs = ctor.call_args.kwargs
            self.assertNotIn("temperature", kwargs)

    def test_cost_from_prices(self) -> None:
        cfg = ModelRegistryConfig(
            provider="openai",
            openai_api_key="k",
            openai_model="m",
            anthropic_api_key="",
            anthropic_model="",
            enterprise_reasoning_override="",
            temperature="",
            price_in_per_mtok="1",
            price_out_per_mtok="2",
        )
        self.assertAlmostEqual(compute_cost_usd(1_000_000, 500_000, cfg), 2.0)

    def test_missing_key_startup_error(self) -> None:
        cfg = ModelRegistryConfig(
            provider="openai",
            openai_api_key="",
            openai_model="gpt-test",
            anthropic_api_key="",
            anthropic_model="",
            enterprise_reasoning_override="",
            temperature="",
            price_in_per_mtok="1",
            price_out_per_mtok="1",
        )
        with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
            validate_real_model_startup(cfg)

    def test_missing_prices_startup_error(self) -> None:
        cfg = ModelRegistryConfig(
            provider="openai",
            openai_api_key="k",
            openai_model="gpt-test",
            anthropic_api_key="",
            anthropic_model="",
            enterprise_reasoning_override="",
            temperature="",
            price_in_per_mtok="",
            price_out_per_mtok="",
        )
        with self.assertRaisesRegex(RuntimeError, "AOS_MODEL_PRICE"):
            validate_real_model_startup(cfg)

    @mock.patch.dict(os.environ, {"AOS_MODEL_PROVIDER": "openai", "OPENAI_MODEL": "gpt-x"}, clear=False)
    def test_load_from_env(self) -> None:
        cfg = load_model_registry_config()
        self.assertEqual(cfg.provider, "openai")
        self.assertEqual(cfg.openai_model, "gpt-x")


@unittest.skipUnless(os.environ.get("AOS_REAL_MODEL") == "1", "manual real-model smoke")
class RealModelSmokeTests(unittest.TestCase):
    def test_registry_validates_with_env(self) -> None:
        validate_real_model_startup()


if __name__ == "__main__":
    unittest.main()
