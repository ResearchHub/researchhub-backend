"""Award-size scope policy shared by the prompt and the scope gate.

A small grant funds one focused specific aim, not a full multi-aim program, and
a reviewer flagged a three-aim draft as far too heavy for a $5k award. The
award's dollar size caps how many specific aims the proposal should carry; the
same policy seeds the agent's prompt and backs the deterministic scope gate so
"how many aims to write" and "how many aims pass" cannot drift apart.
"""

from decimal import Decimal, InvalidOperation

# USD award (inclusive lower bound) -> the most specific aims it should fund,
# highest tier first. Below the lowest tier the award funds a single aim.
_AIM_BUDGET_TIERS = ((Decimal(100_000), 3), (Decimal(50_000), 2))
_MIN_AIMS = 1

_AIM_WORDS = {1: "one specific aim", 2: "two specific aims", 3: "three specific aims"}

# Prose fallback for an unknown award, when the agent must size the aims
# itself; the sub-parts a/b allowance lives in the system prompt template.
_AIM_RULE = (
    "An award under $50k funds one focused specific aim, $50k-$100k funds "
    "two, and above $100k funds three."
)


def _usd_amount(amount: object, currency: object) -> Decimal | None:
    """The award as a positive USD ``Decimal``, or ``None`` when it doesn't apply.

    Returns ``None`` for a missing/unparseable amount, a non-positive amount, or
    a non-USD currency -- the dollar tiers only speak to USD awards.
    """
    if str(currency or "USD").upper() != "USD":
        return None
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return value if value > 0 else None


def max_aims_for_budget(amount: object, currency: object = "USD") -> int | None:
    """Most specific aims an award this size should fund, or ``None`` if unknown.

    ``None`` means the tiers do not apply (missing/non-USD amount): the gate
    imposes no aim cap and the prompt falls back to the general rule.
    """
    value = _usd_amount(amount, currency)
    if value is None:
        return None
    for threshold, aims in _AIM_BUDGET_TIERS:
        if value >= threshold:
            return aims
    return _MIN_AIMS


def format_award(amount: object, currency: object) -> str:
    """Human-readable award amount, e.g. ``$5,000`` for a USD grant."""
    value = _usd_amount(amount, currency)
    if value is not None:
        return f"${value:,.0f}"
    return f"{amount} {currency}".strip()


def aim_scope_guidance(amount: object, currency: object = "USD") -> str:
    """One or two sentences telling the agent how many aims this award funds."""
    max_aims = max_aims_for_budget(amount, currency)
    if max_aims is None:
        return "Size the number of specific aims to the award. " + _AIM_RULE
    return (
        f"This RFP awards {format_award(amount, currency)}, which funds at "
        f"most {_AIM_WORDS[max_aims]}."
    )
