"""Model alias registry (ADR 014)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

PROMPT_VERSION_ASSIST = "assist_v1"
PROMPT_VERSION_TASK = "task_v1"


@dataclass(frozen=True)
class ResolvedModel:
    alias: str
    provider: str
    model_id: str


@dataclass(frozen=True)
class ModelRegistryConfig:
    provider: str
    openai_api_key: str
    openai_model: str
    anthropic_api_key: str
    anthropic_model: str
    enterprise_reasoning_override: str
    temperature: str
    price_in_per_mtok: str
    price_out_per_mtok: str


def load_model_registry_config() -> ModelRegistryConfig:
    return ModelRegistryConfig(
        provider=os.environ.get("AOS_MODEL_PROVIDER", "openai").strip().lower() or "openai",
        openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
        openai_model=os.environ.get("OPENAI_MODEL", "gpt-5.4-mini").strip(),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "").strip(),
        enterprise_reasoning_override=os.environ.get("AOS_MODEL_ENTERPRISE_REASONING", "").strip(),
        temperature=os.environ.get("AOS_MODEL_TEMPERATURE", "").strip(),
        price_in_per_mtok=os.environ.get("AOS_MODEL_PRICE_IN_PER_MTOK", "").strip(),
        price_out_per_mtok=os.environ.get("AOS_MODEL_PRICE_OUT_PER_MTOK", "").strip(),
    )


def resolve_alias(alias: str, cfg: ModelRegistryConfig | None = None) -> ResolvedModel:
    cfg = cfg or load_model_registry_config()
    if alias != "enterprise_reasoning":
        raise RuntimeError(f"unknown model alias {alias!r}")
    if cfg.enterprise_reasoning_override:
        part, _, model = cfg.enterprise_reasoning_override.partition(":")
        if not part or not model:
            raise RuntimeError("AOS_MODEL_ENTERPRISE_REASONING must be provider:model")
        return ResolvedModel(alias=alias, provider=part.strip().lower(), model_id=model.strip())
    if cfg.provider == "anthropic":
        return ResolvedModel(alias=alias, provider="anthropic", model_id=cfg.anthropic_model)
    return ResolvedModel(alias=alias, provider="openai", model_id=cfg.openai_model)


def validate_real_model_startup(cfg: ModelRegistryConfig | None = None) -> ResolvedModel:
    cfg = cfg or load_model_registry_config()
    resolved = resolve_alias("enterprise_reasoning", cfg)
    if resolved.provider == "openai":
        if not cfg.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for AOS_RUNTIME=langgraph with AOS_MODEL_PROVIDER=openai")
        if not cfg.openai_model:
            raise RuntimeError("OPENAI_MODEL is required for AOS_RUNTIME=langgraph")
    elif resolved.provider == "anthropic":
        if not cfg.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for AOS_RUNTIME=langgraph with anthropic")
        if not cfg.anthropic_model:
            raise RuntimeError("ANTHROPIC_MODEL is required for AOS_RUNTIME=langgraph")
    else:
        raise RuntimeError(f"unsupported AOS_MODEL_PROVIDER {resolved.provider!r}")
    if not cfg.price_in_per_mtok or not cfg.price_out_per_mtok:
        raise RuntimeError(
            "AOS_MODEL_PRICE_IN_PER_MTOK and AOS_MODEL_PRICE_OUT_PER_MTOK are required for real-model runs"
        )
    return resolved


def compute_cost_usd(tokens_in: int, tokens_out: int, cfg: ModelRegistryConfig | None = None) -> float:
    cfg = cfg or load_model_registry_config()
    if not cfg.price_in_per_mtok or not cfg.price_out_per_mtok:
        return 0.0
    pin = float(cfg.price_in_per_mtok)
    pout = float(cfg.price_out_per_mtok)
    return (tokens_in * pin + tokens_out * pout) / 1_000_000.0


def build_chat_model(resolved: ResolvedModel, contract: dict[str, Any], cfg: ModelRegistryConfig | None = None):
    cfg = cfg or load_model_registry_config()
    max_tokens = int((contract.get("model") or {}).get("max_output_tokens") or 4096)
    kwargs: dict[str, Any] = {"model": resolved.model_id, "max_tokens": max_tokens}
    if cfg.temperature:
        kwargs["temperature"] = float(cfg.temperature)
    if resolved.provider == "openai":
        from langchain_openai import ChatOpenAI

        kwargs["api_key"] = cfg.openai_api_key
        kwargs["stream_usage"] = True
        return ChatOpenAI(**kwargs)
    if resolved.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kwargs["api_key"] = cfg.anthropic_api_key
        return ChatAnthropic(**kwargs)
    raise RuntimeError(f"unsupported provider {resolved.provider!r}")
