"""
Deterministic scoring for 5-dimension proposal reviews (ported from artemis-api).
"""

import json
import re
from typing import Optional

from ai_peer_review.constants import OverallRating

SCORE_MAP = {"High": 3, "Medium": 2, "Low": 1}
DIMENSION_KEYS = [
    "fundability",
    "feasibility",
    "novelty",
    "impact",
    "reproducibility",
]

DIMENSION_SUB_AREAS = {
    "fundability": ["scope_alignment", "budget_adequacy", "timeline_realism"],
    "feasibility": [
        "investigator_expertise",
        "institutional_capacity",
        "track_record",
    ],
    "novelty": [
        "conceptual_novelty",
        "methodological_novelty",
        "literature_positioning",
    ],
    "impact": [
        "scientific_impact",
        "clinical_translational_impact",
        "societal_broader_impact",
        "community_ecosystem_impact",
    ],
    "reproducibility": [
        "methods_rigor",
        "statistical_analysis_plan",
        "data_code_transparency",
        "gold_standard_methodology",
        "validation_robustness",
    ],
}

OPTIONAL_SUB_AREAS = {
    ("feasibility", "track_record"),
    ("impact", "clinical_translational_impact"),
    ("impact", "community_ecosystem_impact"),
    ("reproducibility", "gold_standard_methodology"),
}

ANSWER_TO_NUMERIC = {
    "yes": 1.0,
    "partial": 0.5,
    "no": 0.0,
}

CRITICAL_FAIL_KEYS = {
    ("fundability", "timeline_realism", "go_no_go_gates"),
    ("reproducibility", "statistical_analysis_plan", "stats_plan"),
    ("reproducibility", "statistical_analysis_plan", "power_analysis"),
    ("reproducibility", "methods_rigor", "methods_detail"),
    ("reproducibility", "methods_rigor", "controls_defined"),
}


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


def normalize_scores_from_answers(review_dict: dict) -> None:
    for dim_key, sub_area_keys in DIMENSION_SUB_AREAS.items():
        dim_obj = review_dict.get(dim_key)
        if not isinstance(dim_obj, dict):
            continue
        sub_area_means = []
        for sub_key in sub_area_keys:
            sub_obj = dim_obj.get(sub_key)
            if not isinstance(sub_obj, dict):
                continue
            is_optional = (dim_key, sub_key) in OPTIONAL_SUB_AREAS
            question_values = []
            answer_keys = [
                k
                for k in sub_obj.keys()
                if k not in {"score", "rationale", "flags"}
            ]
            na_count = 0
            for answer_key in answer_keys:
                raw = sub_obj.get(answer_key)
                numeric_val = _answer_to_numeric(raw)
                if numeric_val is None:
                    if (
                        isinstance(raw, str)
                        and raw.strip().lower() == "n/a"
                    ):
                        na_count += 1
                    continue
                question_values.append(numeric_val)
            if is_optional and answer_keys and na_count == len(answer_keys):
                sub_obj["score"] = "N/A"
                continue
            if not question_values:
                sub_obj["score"] = "Low"
                sub_area_means.append(0.0)
                continue
            mean_val = sum(question_values) / len(question_values)
            score_label = _label_from_mean(mean_val)
            score_label = _cap_sub_area_for_critical_fail(
                dim_key, sub_key, sub_obj, score_label
            )
            sub_obj["score"] = score_label
            sub_area_means.append(mean_val)
        if not sub_area_means:
            dim_obj["overall_score"] = "Low"
            continue
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
