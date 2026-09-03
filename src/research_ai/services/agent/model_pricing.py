"""Reviewed per-token prices for models exposed by the agent catalog."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from research_ai.services.agent.model_capabilities import _normalized
from research_ai.services.agent.providers.registry import split_model_ref
from research_ai.services.agent.types import TurnUsage


@dataclass(frozen=True)
class ModelPricing:
    """USD charged per million tokens for each provider usage bucket."""

    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    cache_read_usd_per_mtok: Decimal
    cache_write_usd_per_mtok: Decimal
    web_search_usd_per_request: Decimal


def _price(
    input_: str,
    output: str,
    cache_read: str,
    cache_write: str,
    web_search: str = "0",
) -> ModelPricing:
    return ModelPricing(
        *(
            Decimal(value)
            for value in (input_, output, cache_read, cache_write, web_search)
        )
    )


# Prices are deliberately keyed by the same normalized ids as model capabilities.
# Updating a vendor rate is one reviewed table edit; historical ledger rows retain
# the price actually applied when their request completed.
_CLAUDE_PLATFORM_PRICING = {
    "claude-opus-5": _price("5", "25", "0.50", "6.25", "0.01"),
    "claude-sonnet-5": _price("2", "10", "0.20", "2.50", "0.01"),
    "claude-haiku-4-5": _price("1", "5", "0.10", "1.25", "0.01"),
}

_OPENROUTER_PRICING = {
    "openai/gpt-5.6-sol": _price("2", "10", "0.20", "2.50"),
    "openai/gpt-5.6-terra": _price("2", "12", "0.20", "2.50"),
    "openai/gpt-5.6-luna": _price("0.20", "1.20", "0.02", "0.25"),
    # No longer selectable, but retained for usage from previously pinned models.
    "google/gemini-3.1-pro-preview": _price("2", "12", "0.20", "0.375"),
    "google/gemini-3.7-flash": _price("0.75", "3.75", "0.075", "0.04167"),
    "google/gemini-3.8-flash": _price("0.75", "3.75", "0.075", "0.04167"),
    "x-ai/grok-4.6": _price("2", "6", "0.50", "2"),
    # Use GLM's undiscounted rates; its launch discount expires September 9, 2026.
    "z-ai/glm-5.3-flash": _price("0.15", "0.50", "0.03", "0.15"),
    "deepseek/deepseek-v4-flash-0731": _price("0.05", "0.16", "0.013", "0.05"),
    "deepseek/deepseek-v4-pro-0813": _price("0.66", "1.98", "0.022", "0.66"),
    "moonshotai/kimi-k3": _price("2.55", "12.75", "0.256", "2.55"),
}

_PROVIDER_PRICING = {
    "claude_platform": _CLAUDE_PLATFORM_PRICING,
    "openrouter": _OPENROUTER_PRICING,
}


def model_pricing(provider: str, model_id: str) -> ModelPricing | None:
    """Return reviewed pricing, or ``None`` when a model is unpriced."""
    return _PROVIDER_PRICING.get(provider, {}).get(_normalized(model_id))


def cost_microusd(provider: str, model_id: str, usage: TurnUsage) -> int | None:
    """Price one normalized provider turn in integer micro-USD.

    A missing provider counter is treated as zero; an absent pricing row is
    different and returns ``None`` so budgeted users can be refused safely.
    """
    pricing = model_pricing(provider, model_id)
    if pricing is None:
        return None
    total = sum(
        (
            Decimal(tokens or 0) * rate
            for tokens, rate in (
                (usage.input_tokens, pricing.input_usd_per_mtok),
                (usage.output_tokens, pricing.output_usd_per_mtok),
                (usage.cache_read_tokens, pricing.cache_read_usd_per_mtok),
                (usage.cache_write_tokens, pricing.cache_write_usd_per_mtok),
            )
        ),
        Decimal(0),
    )
    total += (
        Decimal(usage.web_search_requests or 0)
        * pricing.web_search_usd_per_request
        * Decimal(1_000_000)
    )
    # rate ($ / MTok) * tokens is numerically micro-USD.
    return int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def cost_multiplier(ref: str) -> Decimal | None:
    """Blended input/output price relative to the cheapest catalog model."""
    provider, model_id = split_model_ref(ref)
    pricing = model_pricing(provider, model_id or "")
    if pricing is None:
        return None
    reviewed = [
        price
        for provider_prices in _PROVIDER_PRICING.values()
        for price in provider_prices.values()
    ]
    cheapest = min(
        price.input_usd_per_mtok + price.output_usd_per_mtok for price in reviewed
    )
    blended = pricing.input_usd_per_mtok + pricing.output_usd_per_mtok
    return (blended / cheapest).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
