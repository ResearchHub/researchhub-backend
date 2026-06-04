"""
Generate hot score calculation breakdowns for API responses.

This module creates human-readable explanations of how hot scores are calculated.
All values are dynamically read from HOT_SCORE_CONFIG to ensure breakdowns
automatically update when configuration changes.
"""

from feed.hot_score import HOT_SCORE_CONFIG


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


def _format_signals_from_calc_data(calc_data, config):
    """Format signals dict from calculation data."""
    signal_config = config["signals"]

    return {
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
        "comment": {
            "raw": calc_data["raw_signals"]["comment"],
            "component": calc_data["components"]["comment"],
            "weight": signal_config["comment"]["weight"],
        },
        "recency": {
            "raw": calc_data["raw_signals"]["recency"],
            "component": calc_data["components"]["recency"],
            "weight": signal_config["recency"]["weight"],
        },
        "upvote": {
            "raw": calc_data["raw_signals"]["upvote"],
            "component": calc_data["components"]["upvote"],
            "weight": signal_config["upvote"]["weight"],
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

    age_hours = time_factors["age_hours"]
    base_hours = time_factors["base_hours"]
    gravity = time_factors["gravity"]
    final_score = calculation["final_score"]

    return (
        f"({comp_str}) / "
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
    signal_order = ["bounty", "tip", "peer_review", "comment", "recency", "upvote"]

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
        elif signal_name == "recency":
            steps.append(
                f"  {signal_name:12s} ln({raw_val:.2f} + 1) * {weight} = "
                f"{component:.1f} (time-based)"
            )
        else:
            steps.append(
                f"  {signal_name:12s} ln({raw_val} + 1) * {weight} = {component:.1f}"
            )

    # Add calculation steps with config values
    eng_score = calculation["engagement_score"]
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
            f"Time Decay = ({age:.1f} + {base_hours})^{gravity} = {denom:.1f}",
            f"Raw = {eng_score:.1f} / {denom:.1f} = {raw:.2f}",
            f"Final = int({raw:.2f} * 100) = {final}",
        ]
    )

    return steps
