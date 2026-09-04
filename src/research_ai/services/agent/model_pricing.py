"""Reviewed per-token prices for models exposed by the agent catalog."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from research_ai.services.agent.model_capabilities import _normalized
from research_ai.services.agent.providers.registry import split_model_ref
from research_ai.services.agent.types import TurnUsage

# A fixed reference keeps displayed multipliers stable when the catalog changes.
COST_MULTIPLIER_BASE_MODEL = "openrouter:deepseek/deepseek-v4-flash-0731"


@dataclass(frozen=True)
class TokenPricing:
    """USD charged per million tokens for each provider usage bucket."""

    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    cache_read_usd_per_mtok: Decimal
    cache_write_usd_per_mtok: Decimal


@dataclass(frozen=True)
class PricingOverride:
    """Conditional token rates applied above a prompt-token threshold."""

    min_prompt_tokens: int
    pricing: TokenPricing


@dataclass(frozen=True)
class ModelPricing(TokenPricing):
    """Reviewed token and tool pricing for one provider model."""

    web_search_usd_per_request: Decimal
    override: PricingOverride | None = None


def _price(
    input_: str,
    output: str,
    cache_read: str,
    cache_write: str,
    web_search: str = "0",
    *,
    override_after: int | None = None,
    override: tuple[str, str, str, str] | None = None,
) -> ModelPricing:
    conditional = None
    if override_after is not None and override is not None:
        conditional = PricingOverride(
            min_prompt_tokens=override_after,
            pricing=TokenPricing(*(Decimal(value) for value in override)),
        )
    return ModelPricing(
        *(
            Decimal(value)
            for value in (input_, output, cache_read, cache_write, web_search)
        ),
        override=conditional,
    )


# Sources reviewed 2026-09-02:
# - Claude Platform pricing: https://platform.claude.com/docs/en/about-claude/pricing
# - AWS billing: https://docs.aws.amazon.com/claude-platform/latest/userguide/billing.html
# - OpenRouter live catalog: https://openrouter.ai/api/v1/models
# - OpenRouter usage cost: https://openrouter.ai/docs/cookbook/administration/usage-accounting
# Prices are keyed by the same normalized ids as model capabilities. Historical
# ledger rows retain the charge applied when their request completed.
_CLAUDE_PLATFORM_PRICING = {
    "claude-opus-5": _price("5", "25", "0.50", "6.25", "0.01"),
    "claude-sonnet-5": _price("2", "10", "0.20", "2.50", "0.01"),
    "claude-haiku-4-5": _price("1", "5", "0.10", "1.25", "0.01"),
}

_OPENROUTER_PRICING = {
    "openai/gpt-5.6-sol": _price(
        "2",
        "10",
        "0.20",
        "2.50",
        "0.01",
        override_after=272_000,
        override=("4", "15", "0.40", "5"),
    ),
    "openai/gpt-5.6-terra": _price(
        "2",
        "12",
        "0.20",
        "2.50",
        "0.01",
        override_after=272_000,
        override=("4", "18", "0.40", "5"),
    ),
    "openai/gpt-5.6-luna": _price(
        "0.20",
        "1.20",
        "0.02",
        "0.25",
        "0.01",
        override_after=272_000,
        override=("0.40", "1.80", "0.04", "0.50"),
    ),
    "google/gemini-3.1-pro-preview": _price(
        "2",
        "12",
        "0.20",
        "0.375",
        "0.014",
        override_after=200_000,
        override=("4", "18", "0.40", "0.375"),
    ),
    "google/gemini-3.7-flash": _price(
        "0.75", "3.75", "0.075", "0.0416666666666666666667", "0.014"
    ),
    "google/gemini-3.8-flash": _price("0.75", "3.75", "0.075", "0.04167"),
    "x-ai/grok-4.6": _price(
        "2",
        "6",
        "0.50",
        "0",
        "0.005",
        override_after=200_000,
        override=("4", "12", "1", "0"),
    ),
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
    if usage.provider_cost_microusd is not None:
        return usage.provider_cost_microusd
    pricing = model_pricing(provider, model_id)
    if pricing is None:
        return None
    prompt_tokens = sum(
        tokens or 0
        for tokens in (
            usage.input_tokens,
            usage.cache_read_tokens,
            usage.cache_write_tokens,
        )
    )
    token_pricing: TokenPricing = pricing
    if (
        pricing.override is not None
        and prompt_tokens > pricing.override.min_prompt_tokens
    ):
        token_pricing = pricing.override.pricing
    total = sum(
        (
            Decimal(tokens or 0) * rate
            for tokens, rate in (
                (usage.input_tokens, token_pricing.input_usd_per_mtok),
                (usage.output_tokens, token_pricing.output_usd_per_mtok),
                (usage.cache_read_tokens, token_pricing.cache_read_usd_per_mtok),
                (usage.cache_write_tokens, token_pricing.cache_write_usd_per_mtok),
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
    """Estimated relative cost for equal uncached input and output tokens.

    This comparison excludes cache and search charges. Actual credits use each
    usage bucket's rate, not this rounded multiplier.
    """
    provider, model_id = split_model_ref(ref)
    pricing = model_pricing(provider, model_id or "")
    if pricing is None:
        return None
    base_provider, base_model_id = split_model_ref(COST_MULTIPLIER_BASE_MODEL)
    base = model_pricing(base_provider, base_model_id or "")
    if base is None:
        return None
    baseline = base.input_usd_per_mtok + base.output_usd_per_mtok
    blended = pricing.input_usd_per_mtok + pricing.output_usd_per_mtok
    return (blended / baseline).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
