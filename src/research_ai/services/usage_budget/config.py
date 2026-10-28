"""Code-owned Research AI tier policies."""

from dataclasses import dataclass, replace

# What a new chat or draft runs when the user picks no model, in every tier.
DEFAULT_MODEL = "openrouter:openai/gpt-6.1-sol"
# Former defaults: default-tier chats already pinned to them keep running.
LEGACY_DEFAULT_TIER_MODELS = (
    "claude_platform:claude-opus-5-5",
    "openrouter:deepseek/deepseek-v4-flash-0731",
)
BUDGETS_ENFORCED = True
# Usage recorded under these features spends the daily dollar budget but never
# counts as a turn.
COVER_IMAGE_FEATURE = "cover_image_generation"
DOLLAR_ONLY_FEATURES = frozenset({COVER_IMAGE_FEATURE})
MAX_IN_FLIGHT_JOBS_PER_USER = 5
DEFAULT_DAILY_BUDGET_MICROUSD = 1_000_000
# Shared by every default-tier user combined, on top of the per-user budget.
DEFAULT_POOL_DAILY_BUDGET_MICROUSD = 1_000_000_000
INVITED_DAILY_BUDGET_MICROUSD = 10_000_000
PRIVILEGED_DAILY_BUDGET_MICROUSD = 100_000_000


@dataclass(frozen=True)
class TierPolicy:
    name: str
    daily_budget_microusd: int | None
    daily_turn_cap: int | None
    allowed_model_refs: tuple[str, ...] | None
    default_model_ref: str | None
    max_effort: str | None = None
    allowed_thinking_modes: tuple[str, ...] | None = None
    pool_daily_budget_microusd: int | None = None

    @property
    def is_budgeted(self) -> bool:
        return (
            self.daily_budget_microusd is not None
            or self.daily_turn_cap is not None
            or self.pool_daily_budget_microusd is not None
        )


def tier_policies() -> dict[str, TierPolicy]:
    """Build fresh policy values for each resolution."""
    default = TierPolicy(
        name="default",
        daily_budget_microusd=DEFAULT_DAILY_BUDGET_MICROUSD,
        daily_turn_cap=None,
        allowed_model_refs=(DEFAULT_MODEL, *LEGACY_DEFAULT_TIER_MODELS),
        default_model_ref=DEFAULT_MODEL,
        # The lowest effort of Sol and Opus 5.5. Thinking is left to each model:
        # both only think adaptively, and DeepSeek runs with effort "none".
        max_effort="low",
        pool_daily_budget_microusd=DEFAULT_POOL_DAILY_BUDGET_MICROUSD,
    )
    invited = TierPolicy(
        name="invited",
        daily_budget_microusd=INVITED_DAILY_BUDGET_MICROUSD,
        daily_turn_cap=None,
        allowed_model_refs=None,
        default_model_ref=DEFAULT_MODEL,
    )
    privileged = TierPolicy(
        name="privileged",
        daily_budget_microusd=PRIVILEGED_DAILY_BUDGET_MICROUSD,
        daily_turn_cap=None,
        allowed_model_refs=None,
        default_model_ref=DEFAULT_MODEL,
    )
    blocked = TierPolicy("blocked", 0, 0, (), None)
    # ``replace`` keeps policies independent even if future defaults share fields.
    return {
        policy.name: replace(policy)
        for policy in (blocked, privileged, invited, default)
    }
