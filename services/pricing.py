from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_per_million_usd: float
    output_per_million_usd: float
    cached_input_per_million_usd: float | None = None


BUILTIN_MODEL_PRICING: dict[str, ModelPricing] = {
    "gpt-4o-mini-tts": ModelPricing(input_per_million_usd=0.6, output_per_million_usd=12.0),
    "gpt-5.2": ModelPricing(input_per_million_usd=1.75, cached_input_per_million_usd=0.175, output_per_million_usd=14.0),
    "gpt-5.2-chat-latest": ModelPricing(input_per_million_usd=1.75, cached_input_per_million_usd=0.175, output_per_million_usd=14.0),
    "gpt-5.2-pro": ModelPricing(input_per_million_usd=21.0, cached_input_per_million_usd=None, output_per_million_usd=168.0),
    "gpt-5.1": ModelPricing(input_per_million_usd=1.25, cached_input_per_million_usd=0.125, output_per_million_usd=10.0),
    "gpt-5.1-chat-latest": ModelPricing(input_per_million_usd=1.25, cached_input_per_million_usd=0.125, output_per_million_usd=10.0),
    "gpt-5": ModelPricing(input_per_million_usd=1.25, cached_input_per_million_usd=0.125, output_per_million_usd=10.0),
    "gpt-5-chat-latest": ModelPricing(input_per_million_usd=1.25, cached_input_per_million_usd=0.125, output_per_million_usd=10.0),
    "gpt-5-pro": ModelPricing(input_per_million_usd=15.0, cached_input_per_million_usd=None, output_per_million_usd=120.0),
    "gpt-5-mini": ModelPricing(input_per_million_usd=0.25, cached_input_per_million_usd=0.025, output_per_million_usd=2.0),
    "gpt-5-nano": ModelPricing(input_per_million_usd=0.05, cached_input_per_million_usd=0.005, output_per_million_usd=0.4),
    "gpt-4.1": ModelPricing(input_per_million_usd=2.0, cached_input_per_million_usd=0.5, output_per_million_usd=8.0),
    "gpt-4.1-mini": ModelPricing(input_per_million_usd=0.4, cached_input_per_million_usd=0.1, output_per_million_usd=1.6),
    "gpt-4o": ModelPricing(input_per_million_usd=2.5, cached_input_per_million_usd=1.25, output_per_million_usd=10.0),
    "gpt-4o-mini": ModelPricing(input_per_million_usd=0.15, cached_input_per_million_usd=0.075, output_per_million_usd=0.6),
    "o3": ModelPricing(input_per_million_usd=2.0, cached_input_per_million_usd=0.5, output_per_million_usd=8.0),
    "o4-mini": ModelPricing(input_per_million_usd=1.1, cached_input_per_million_usd=0.275, output_per_million_usd=4.4),
    "tts-1": ModelPricing(input_per_million_usd=15.0, output_per_million_usd=0.0),
    "tts-1-hd": ModelPricing(input_per_million_usd=30.0, output_per_million_usd=0.0),
}


def resolve_model_pricing(model: str, overrides: dict[str, ModelPricing]) -> ModelPricing | None:
    if model in overrides:
        return overrides[model]
    if model in BUILTIN_MODEL_PRICING:
        return BUILTIN_MODEL_PRICING[model]

    for candidate_model, pricing in overrides.items():
        if model.startswith(candidate_model + "-"):
            return pricing

    for candidate_model, pricing in BUILTIN_MODEL_PRICING.items():
        if model.startswith(candidate_model + "-"):
            return pricing

    return None


def estimate_cost_usd(
    *,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    pricing: ModelPricing | None,
) -> float | None:
    if pricing is None:
        return None

    cached_tokens = max(0, min(cached_input_tokens, input_tokens))
    uncached_tokens = max(0, input_tokens - cached_tokens)
    cached_rate = pricing.cached_input_per_million_usd
    if cached_rate is None:
        cached_rate = pricing.input_per_million_usd

    input_cost = (uncached_tokens * pricing.input_per_million_usd) / 1_000_000
    cached_input_cost = (cached_tokens * cached_rate) / 1_000_000
    output_cost = (max(0, output_tokens) * pricing.output_per_million_usd) / 1_000_000
    return input_cost + cached_input_cost + output_cost
