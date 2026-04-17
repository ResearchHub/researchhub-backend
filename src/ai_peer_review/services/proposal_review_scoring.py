import json
import re
from typing import Optional

from ai_peer_review.constants import (
    DIMENSION_KEYS,
    DIMENSION_SUB_AREAS,
    OPTIONAL_SUB_AREAS,
)
from ai_peer_review.models import OverallRating

SCORE_MAP = {"High": 3, "Medium": 2, "Low": 1}

ANSWER_TO_NUMERIC = {
    "yes": 1.0,
    "partial": 0.5,
    "no": 0.0,
}

# Keep in sync with proposal_review_system.txt (Critical fail cap rule)
CRITICAL_FAIL_KEYS = {
    ("fundability", "timeline_realism", "go_no_go_gates"),
    ("reproducibility", "statistical_analysis_plan", "stats_plan"),
    ("reproducibility", "statistical_analysis_plan", "power_analysis"),
    ("reproducibility", "methods_rigor", "methods_detail"),
    ("reproducibility", "methods_rigor", "controls_defined"),
}

_RESERVED_SUB_AREA_KEYS = frozenset({"score", "rationale", "flags"})


def parse_json_response(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if code_block:
        try:
            return json.loads(code_block.group(1))
        except json.JSONDecodeError:
            pass
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError("Could not extract valid JSON from LLM response")


def _label_from_mean(mean_value: float) -> str:
    if mean_value >= 0.75:
        return "High"
    if mean_value >= 0.40:
        return "Medium"
    return "Low"


def _answer_to_numeric(value: Optional[str]) -> Optional[float]:
    if not isinstance(value, str):
        return None
    value_lower = value.strip().lower()
    if value_lower == "n/a":
        return None
    return ANSWER_TO_NUMERIC.get(value_lower)


# Extra guard against critical fail rule violation
def _cap_sub_area_for_critical_fail(
    dim_key: str,
    sub_key: str,
    sub_area_data: dict,
    current_label: str,
) -> str:
    if current_label != "High":
        return current_label
    for d, s, q in CRITICAL_FAIL_KEYS:
        if d != dim_key or s != sub_key:
            continue
        q_val = sub_area_data.get(q)
        if isinstance(q_val, str) and q_val.strip().lower() == "no":
            return "Medium"
    return current_label


def _answer_keys_in_sub_area(sub_obj: dict) -> list[str]:
    return [k for k in sub_obj.keys() if k not in _RESERVED_SUB_AREA_KEYS]


def _gather_numeric_answers(
    sub_obj: dict, answer_keys: list[str]
) -> tuple[list[float], int]:
    """Collect yes/partial/no as floats; ``na_count`` is explicit ``n/a`` answers only."""
    question_values: list[float] = []
    na_count = 0
    for answer_key in answer_keys:
        raw = sub_obj.get(answer_key)
        numeric_val = _answer_to_numeric(raw)
        if numeric_val is not None:
            question_values.append(numeric_val)
            continue
        if isinstance(raw, str) and raw.strip().lower() == "n/a":
            na_count += 1
    return question_values, na_count


def _sub_area_contribution_to_dimension_mean(
    dim_key: str,
    sub_key: str,
    sub_obj: dict,
    is_optional: bool,
) -> Optional[float]:
    """Write ``sub_obj['score']``; return mean for dimension rollup, or ``None`` if excluded."""
    answer_keys = _answer_keys_in_sub_area(sub_obj)
    question_values, na_count = _gather_numeric_answers(sub_obj, answer_keys)

    if is_optional and answer_keys and na_count == len(answer_keys):
        sub_obj["score"] = "N/A"
        return None

    if not question_values:
        sub_obj["score"] = "Low"
        return 0.0

    mean_val = sum(question_values) / len(question_values)
    score_label = _label_from_mean(mean_val)
    score_label = _cap_sub_area_for_critical_fail(
        dim_key, sub_key, sub_obj, score_label
    )
    sub_obj["score"] = score_label
    return mean_val


def normalize_scores_from_answers(review_dict: dict) -> None:
    """Derive High/Medium/Low (or N/A for optional rows) from raw LLM answers, in place.

    ``review_dict`` matches the structured review shape: each dimension is a dict of
    sub-area dicts. Sub-areas hold yes/partial/no (and metadata keys ``score``,
    ``rationale``, ``flags``). This walk:

    1. For each sub-area, averages numeric equivalents of question fields, maps the
       mean to a label, writes ``sub_obj["score"]``, and records the mean for rollup.
    2. Optional sub-areas whose every answer is ``n/a`` get ``score`` ``N/A`` and
       are excluded from the dimension mean (not appended to ``sub_area_means``).
    3. Sub-areas with no usable numeric answers default to ``Low`` and contribute
       ``0.0`` so they still pull the dimension down.
    4. Each dimension's ``overall_score`` is the label for the mean of sub-area
       means (or ``Low`` if nothing contributed).
    """
    for dim_key, sub_area_keys in DIMENSION_SUB_AREAS.items():
        dim_obj = review_dict.get(dim_key)
        if not isinstance(dim_obj, dict):
            continue

        sub_area_means: list[float] = []
        for sub_key in sub_area_keys:
            sub_obj = dim_obj.get(sub_key)
            if not isinstance(sub_obj, dict):
                continue
            is_optional = (dim_key, sub_key) in OPTIONAL_SUB_AREAS
            contribution = _sub_area_contribution_to_dimension_mean(
                dim_key, sub_key, sub_obj, is_optional
            )
            if contribution is not None:
                sub_area_means.append(contribution)

        if not sub_area_means:
            dim_obj["overall_score"] = "Low"
        else:
            dim_mean = sum(sub_area_means) / len(sub_area_means)
            dim_obj["overall_score"] = _label_from_mean(dim_mean)


def compute_overall_rating(review_dict: dict) -> tuple[str, int]:
    total = 0
    for dim_key in DIMENSION_KEYS:
        dim = review_dict.get(dim_key, {})
        score = dim.get("overall_score", "Low")
        total += SCORE_MAP.get(score, 1)
    if total >= 13:
        rating = OverallRating.EXCELLENT.value
    elif total >= 8:
        rating = OverallRating.GOOD.value
    else:
        rating = OverallRating.POOR.value
    return rating, total


def dimension_overall_scores(review_dict: dict) -> dict[str, Optional[str]]:
    out = {}
    for dim_key in DIMENSION_KEYS:
        dim = review_dict.get(dim_key)
        if isinstance(dim, dict):
            out[dim_key] = dim.get("overall_score")
        else:
            out[dim_key] = None
    return out
