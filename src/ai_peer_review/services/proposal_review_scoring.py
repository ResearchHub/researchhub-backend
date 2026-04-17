import json
import re
from typing import Optional

from ai_peer_review.constants import CATEGORY_KEYS, OPTIONAL_CATEGORIES
from ai_peer_review.models import OverallRating

SCORE_MAP = {"High": 3, "Medium": 2, "Low": 1}

_SCORE_ALIASES = {
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "n/a": "N/A",
    "na": "N/A",
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


def _canonical_category_score(cat_key: str, raw) -> str:
    """Map LLM text to stored category score; ``N/A`` only allowed for optional categories."""
    if not isinstance(raw, str):
        return "Low"
    key = raw.strip().lower()
    label = _SCORE_ALIASES.get(key)
    if label is None:
        return "Low"
    if label == "N/A" and cat_key not in OPTIONAL_CATEGORIES:
        return "Low"
    return label


def normalize_scores_from_answers(review_dict: dict) -> None:
    """Canonicalize ``categories[*].score`` from the LLM in place (no item-level recompute)."""
    cats = review_dict.get("categories")
    if not isinstance(cats, dict):
        return
    for cat_key in CATEGORY_KEYS:
        cat_obj = cats.get(cat_key)
        if not isinstance(cat_obj, dict):
            continue
        cat_obj["score"] = _canonical_category_score(cat_key, cat_obj.get("score"))


def _category_score_label(categories: dict, cat_key: str) -> Optional[str]:
    obj = categories.get(cat_key)
    if not isinstance(obj, dict):
        return None
    score = obj.get("score")
    if score in ("High", "Medium", "Low", "N/A"):
        return score
    return None


def _mean_applicable_category_numerics(review_dict: dict) -> Optional[float]:
    cats = review_dict.get("categories")
    if not isinstance(cats, dict):
        return None
    vals: list[int] = []
    for key in CATEGORY_KEYS:
        lab = _category_score_label(cats, key)
        if lab in SCORE_MAP:
            vals.append(SCORE_MAP[lab])
    if not vals:
        return None
    return sum(vals) / len(vals)


def _canonical_overall_rating(raw) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    s = raw.strip().lower()
    if s in OverallRating.values:
        return s
    return None


def _canonical_overall_score_numeric(raw) -> Optional[int]:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return min(3, max(1, int(v + 0.5)))


def recompute_overall_fields(review_dict: dict) -> None:
    """
    Prefer LLM ``overall_rating`` / ``overall_score_numeric`` after canonicalization.
    """
    rating = _canonical_overall_rating(review_dict.get("overall_rating"))
    review_dict["overall_rating"] = rating

    raw_num = review_dict.get("overall_score_numeric")
    if isinstance(raw_num, bool):
        raw_num = None
    numeric = _canonical_overall_score_numeric(raw_num)
    if numeric is None:
        mean = _mean_applicable_category_numerics(review_dict)
        numeric = min(3, max(1, int(mean + 0.5))) if mean is not None else 1
    review_dict["overall_score_numeric"] = numeric


def category_scores(review_dict: dict) -> dict[str, Optional[str]]:
    """Return each category ``score`` label (``High``/``Medium``/``Low``/``N/A``) after normalization."""
    out: dict[str, Optional[str]] = {}
    cats = review_dict.get("categories")
    if not isinstance(cats, dict):
        for key in CATEGORY_KEYS:
            out[key] = None
        return out
    for key in CATEGORY_KEYS:
        out[key] = _category_score_label(cats, key)
    return out
