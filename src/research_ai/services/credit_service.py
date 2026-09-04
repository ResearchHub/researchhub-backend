"""Customer-facing credit amounts derived from the provider-cost ledger.

Credits are a display unit, not a second balance or a per-call charge. Keep
fractional credits so small calls do not round up to a whole credit each.
"""

from decimal import Decimal

from research_ai.services.agent.model_pricing import TokenPricing, model_pricing
from research_ai.services.agent.providers.registry import split_model_ref

CREDITS_PER_USD = Decimal(1000)
MICROUSD_PER_USD = Decimal(1000000)


def credits_from_microusd(value: int | None) -> str | None:
    """Serialize an exact credit amount; None means no limit or unknown cost."""
    if value is None:
        return None
    return format(Decimal(value) * CREDITS_PER_USD / MICROUSD_PER_USD, "f")


def _token_credit_rates(pricing: TokenPricing) -> dict[str, str]:
    return {
        key: format(rate * CREDITS_PER_USD, "f")
        for key, rate in (
            ("input_per_million_tokens", pricing.input_usd_per_mtok),
            ("output_per_million_tokens", pricing.output_usd_per_mtok),
            ("cache_read_per_million_tokens", pricing.cache_read_usd_per_mtok),
            ("cache_write_per_million_tokens", pricing.cache_write_usd_per_mtok),
        )
    }


def model_credit_rates(model_ref: str) -> dict | None:
    """Estimated credit rates, including conditional long-context pricing."""
    provider, model_id = split_model_ref(model_ref)
    pricing = model_pricing(provider, model_id or "")
    if pricing is None:
        return None
    rates = {
        **_token_credit_rates(pricing),
        "web_search_per_request": format(
            pricing.web_search_usd_per_request * CREDITS_PER_USD, "f"
        ),
    }
    if pricing.override is not None:
        rates["long_context"] = {
            "prompt_tokens_above": pricing.override.min_prompt_tokens,
            "credit_rates": _token_credit_rates(pricing.override.pricing),
        }
    return rates
