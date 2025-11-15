"""
Generate hot score calculation breakdowns for API responses.

This module creates human-readable explanations of how hot scores are calculated.
All values are dynamically read from HOT_SCORE_CONFIG to ensure breakdowns
automatically update when configuration changes.
"""

from feed.hot_score import HOT_SCORE_CONFIG


def get_hot_score_breakdown(feed_entry):
    """
    Get detailed breakdown of hot score calculation with equation and steps.

    Uses stored breakdown if available, otherwise calculates it using
    calculate_hot_score() as single source of truth.

    Args:
        feed_entry: FeedEntry instance

    Returns:
        dict with formatted breakdown
    """
    # Use stored breakdown if available
    if (
        hasattr(feed_entry, "hot_score_breakdown_v2")
        and feed_entry.hot_score_breakdown_v2
    ):
        return feed_entry.hot_score_breakdown_v2.breakdown_data

    # Otherwise calculate it
    from django.contrib.contenttypes.models import ContentType

    from feed.hot_score import calculate_hot_score

    # Get content type
    item = feed_entry.item
    if not item:
        return _empty_breakdown()

    item_content_type = ContentType.objects.get_for_model(item)

    # Calculate score with components (single source of truth)
    calc_data = calculate_hot_score(
        feed_entry, item_content_type, return_components=True
    )

    if not calc_data:
        return _empty_breakdown()

    # Format and return breakdown
    return format_breakdown_from_calc_data(calc_data)


def format_breakdown_from_calc_data(calc_data):
    """
    Format calculation data into breakdown structure.

    Args:
        calc_data: Dict returned from calculate_hot_score(return_components=True)

    Returns:
        dict with formatted breakdown
    """
    config = HOT_SCORE_CONFIG

    # Format signals from calc_data
    signals = _format_signals_from_calc_data(calc_data, config)

    # Extract time factors
    time_factors = calc_data["time_factors"]

    # Format calculation
    calculation = {
        "engagement_score": calc_data["engagement_score"],
        "adjusted_engagement": calc_data["engagement_score"],
        "time_denominator": calc_data["time_denominator"],
        "raw_score": calc_data["raw_score"],
        "final_score": calc_data["final_score"],
    }

    # Format output
    equation = _format_equation(signals, time_factors, calculation, config)
    steps = _format_steps(signals, time_factors, calculation, config)

    return {
        "equation": equation,
        "steps": steps,
        "signals": signals,
        "time_factors": time_factors,
        "calculation": calculation,
        "config_snapshot": {
            "signal_weights": {k: v["weight"] for k, v in config["signals"].items()},
            "gravity": config["time_decay"]["gravity"],
            "base_hours": config["time_decay"]["base_hours"],
        },
    }


def _empty_breakdown():
    """Return empty breakdown structure for entries without items."""
    return {
        "equation": "",
        "steps": [],
        "signals": {},
        "time_factors": {},
        "calculation": {},
        "config_snapshot": {},
    }


def _format_signals_from_calc_data(calc_data, config):
    """Format signals dict from calculation data."""
    signal_config = config["signals"]

    return {
        "altmetric": {
            "raw": calc_data["raw_signals"]["altmetric"],
            "component": calc_data["components"]["altmetric"],
            "weight": signal_config["altmetric"]["weight"],
        },
        "bounty": {
            "raw": calc_data["raw_signals"]["bounty"],
            "component": calc_data["components"]["bounty"],
            "weight": signal_config["bounty"]["weight"],
            "urgent": calc_data["bounty_urgent"],
            "urgency_multiplier": calc_data["bounty_multiplier"],
        },
        "tip": {
            "raw": calc_data["raw_signals"]["tip"],
            "component": calc_data["components"]["tip"],
            "weight": signal_config["tip"]["weight"],
        },
        "peer_review": {
            "raw": calc_data["raw_signals"]["peer_review"],
            "component": calc_data["components"]["peer_review"],
            "weight": signal_config["peer_review"]["weight"],
        },
        "upvote": {
            "raw": calc_data["raw_signals"]["upvote"],
            "component": calc_data["components"]["upvote"],
            "weight": signal_config["upvote"]["weight"],
        },
        "comment": {
            "raw": calc_data["raw_signals"]["comment"],
            "component": calc_data["components"]["comment"],
            "weight": signal_config["comment"]["weight"],
        },
    }


def _format_equation(signals, time_factors, calculation, config):
    """
    Build compact equation string dynamically from config and values.

    Returns:
        str: Human-readable equation
    """
    # Build component sum
    components = [s["component"] for s in signals.values()]
    comp_str = " + ".join([f"{c:.1f}" for c in components])

    freshness = time_factors["freshness_multiplier"]
    age_hours = time_factors["age_hours"]
    base_hours = time_factors["base_hours"]
    gravity = time_factors["gravity"]
    final_score = calculation["final_score"]

    return (
        f"(({comp_str}) * {freshness:.2f}) / "
        f"({age_hours:.1f} + {base_hours})^{gravity} * 100 = {final_score}"
    )


def _format_steps(signals, time_factors, calculation, config):
    """
    Build step-by-step breakdown dynamically from config and values.

    Returns:
        list of str: Step-by-step calculation
    """
    steps = ["Engagement Components:"]

    # Add each signal component with config values
    signal_order = ["altmetric", "bounty", "tip", "peer_review", "upvote", "comment"]

    for signal_name in signal_order:
        signal_data = signals[signal_name]
        raw_val = signal_data["raw"]
        weight = signal_data["weight"]
        component = signal_data["component"]

        # Build formula string with config values
        if signal_name == "bounty" and signal_data.get("urgent"):
            urgency = signal_data["urgency_multiplier"]
            steps.append(
                f"  {signal_name:12s} ln({raw_val} + 1) * {weight} * {urgency} = "
                f"{component:.1f} (URGENT)"
            )
        else:
            steps.append(
                f"  {signal_name:12s} ln({raw_val} + 1) * {weight} = {component:.1f}"
            )

    # Add calculation steps with config values
    eng_score = calculation["engagement_score"]
    fresh = time_factors["freshness_multiplier"]
    adj_eng = calculation["adjusted_engagement"]
    age = time_factors["age_hours"]
    base_hours = time_factors["base_hours"]
    gravity = time_factors["gravity"]
    denom = calculation["time_denominator"]
    raw = calculation["raw_score"]
    final = calculation["final_score"]

    steps.extend(
        [
            "",
            f"Engagement Score = {eng_score:.1f}",
            f"Freshness Boost = {fresh:.2f}x",
            f"Adjusted = {eng_score:.1f} * {fresh:.2f} = {adj_eng:.1f}",
            f"Time Decay = ({age:.1f} + {base_hours})^{gravity} = {denom:.1f}",
            f"Raw = {adj_eng:.1f} / {denom:.1f} = {raw:.2f}",
            f"Final = int({raw:.2f} * 100) = {final}",
        ]
    )

    return steps
