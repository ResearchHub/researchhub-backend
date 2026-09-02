"""Code-owned Research AI tier policies."""

from dataclasses import dataclass, replace

DEFAULT_OPEN_WEIGHT_MODEL = "openrouter:deepseek/deepseek-v4-pro-0813"
BUDGETS_ENFORCED = True
DEFAULT_DAILY_BUDGET_MICROUSD = 250_000
DEFAULT_DAILY_TURN_CAP = 10
INVITED_DAILY_BUDGET_MICROUSD = 10_000_000
INVITED_DAILY_TURN_CAP = 200
PRIVILEGED_DAILY_BUDGET_MICROUSD = 100_000_000
PRIVILEGED_DAILY_TURN_CAP = 2000


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


def tier_policies() -> dict[str, TierPolicy]:
    """Build fresh policy values for each resolution."""
    default = TierPolicy(
        name="default",
        daily_budget_microusd=DEFAULT_DAILY_BUDGET_MICROUSD,
        daily_turn_cap=DEFAULT_DAILY_TURN_CAP,
        allowed_model_refs=(DEFAULT_OPEN_WEIGHT_MODEL,),
        default_model_ref=DEFAULT_OPEN_WEIGHT_MODEL,
        max_effort="none",
        allowed_thinking_modes=("disabled",),
    )
    invited = TierPolicy(
        name="invited",
        daily_budget_microusd=INVITED_DAILY_BUDGET_MICROUSD,
        daily_turn_cap=INVITED_DAILY_TURN_CAP,
        allowed_model_refs=None,
        default_model_ref=None,
    )
    privileged = TierPolicy(
        name="privileged",
        daily_budget_microusd=PRIVILEGED_DAILY_BUDGET_MICROUSD,
        daily_turn_cap=PRIVILEGED_DAILY_TURN_CAP,
        allowed_model_refs=None,
        default_model_ref=None,
    )
    blocked = TierPolicy("blocked", 0, 0, (), None)
    # ``replace`` keeps policies independent even if future defaults share fields.
    return {
        policy.name: replace(policy)
        for policy in (blocked, privileged, invited, default)
    }
