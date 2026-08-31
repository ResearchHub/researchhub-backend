"""Settings-backed Research AI tier policies."""

from dataclasses import dataclass, replace
from decimal import Decimal

from django.conf import settings

DEFAULT_OPEN_WEIGHT_MODEL = "openrouter:deepseek/deepseek-v4-pro-0813"


@dataclass(frozen=True)
class TierPolicy:
    name: str
    daily_budget_microusd: int | None
    daily_turn_cap: int | None
    allowed_model_refs: tuple[str, ...] | None
    default_model_ref: str | None
    max_effort: str | None = None
    allowed_thinking_modes: tuple[str, ...] | None = None

    @property
    def is_budgeted(self) -> bool:
        return self.daily_budget_microusd is not None or self.daily_turn_cap is not None


def _setting(name: str, default):
    return getattr(settings, name, default)


def _tuple_setting(name: str, default: tuple[str, ...] | None):
    value = _setting(name, default)
    if value is None:
        return None
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return tuple(value)


def _budget_microusd(tier: str, default: int | None) -> int | None:
    prefix = f"RESEARCH_AI_TIER_{tier.upper()}"
    explicit = getattr(settings, f"{prefix}_DAILY_BUDGET_MICROUSD", None)
    if explicit is not None:
        return int(explicit)
    usd = getattr(settings, f"{prefix}_DAILY_BUDGET_USD", None)
    if usd is not None:
        return int(Decimal(str(usd)) * Decimal(1000000))
    return default


def _optional_int_setting(name: str, default: int | None) -> int | None:
    value = _setting(name, default)
    return None if value is None else int(value)


def tier_policies() -> dict[str, TierPolicy]:
    """Build fresh policies so ``override_settings`` works in every test/call."""
    default = TierPolicy(
        name="default",
        daily_budget_microusd=_budget_microusd("default", 250_000),
        daily_turn_cap=_optional_int_setting(
            "RESEARCH_AI_TIER_DEFAULT_DAILY_TURN_CAP", 10
        ),
        allowed_model_refs=_tuple_setting(
            "RESEARCH_AI_TIER_DEFAULT_ALLOWED_MODEL_REFS",
            (DEFAULT_OPEN_WEIGHT_MODEL,),
        ),
        default_model_ref=_setting(
            "RESEARCH_AI_TIER_DEFAULT_DEFAULT_MODEL_REF",
            DEFAULT_OPEN_WEIGHT_MODEL,
        ),
        max_effort=_setting("RESEARCH_AI_TIER_DEFAULT_MAX_EFFORT", "none"),
        allowed_thinking_modes=_tuple_setting(
            "RESEARCH_AI_TIER_DEFAULT_ALLOWED_THINKING_MODES", ("disabled",)
        ),
    )
    privileged = TierPolicy(
        name="privileged",
        daily_budget_microusd=_budget_microusd("privileged", 10_000_000),
        daily_turn_cap=_optional_int_setting(
            "RESEARCH_AI_TIER_PRIVILEGED_DAILY_TURN_CAP", 200
        ),
        allowed_model_refs=_tuple_setting(
            "RESEARCH_AI_TIER_PRIVILEGED_ALLOWED_MODEL_REFS", None
        ),
        default_model_ref=_setting(
            "RESEARCH_AI_TIER_PRIVILEGED_DEFAULT_MODEL_REF", None
        ),
    )
    unlimited = TierPolicy("unlimited", None, None, None, None)
    blocked = TierPolicy("blocked", 0, 0, (), None)
    # ``replace`` keeps policies independent even if future defaults share fields.
    return {
        policy.name: replace(policy)
        for policy in (blocked, unlimited, privileged, default)
    }
