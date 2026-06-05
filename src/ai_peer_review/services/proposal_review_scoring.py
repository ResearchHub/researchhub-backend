import json
import re
from typing import Optional

from ai_peer_review.constants import CATEGORY_ITEMS, CATEGORY_KEYS, CRITICAL_FAIL_ITEMS
from ai_peer_review.models import OverallRating


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


def _decision_to_score_value(decision: object) -> Optional[float]:
    """
    Map one item ``decision`` to a 1-5 scale value for averaging.

    Unknown values return ``None``.
    """
    if not isinstance(decision, str):
        return None
    key = decision.strip().lower()
    if key == "yes":
        return 5.0
    if key == "partial":
        return 3.0
    if key == "no":
        return 1.0
    return None


def _critical_fail_cap_int(cat_key: str, items: dict, score: int) -> int:
    """
    If any critical item is ``No``, ``rigor_and_feasibility`` cannot be 5
    (cap to 4) when any such item is ``No``.
    """
    if score < 5:
        return score
    for ckey, ikey in CRITICAL_FAIL_ITEMS:
        if ckey != cat_key:
            continue
        item = items.get(ikey)
        if not isinstance(item, dict):
            continue
        raw = item.get("decision")
        if isinstance(raw, str) and raw.strip().lower() == "no":
            return 4
    return score


def _gather_item_numerics(cat_key: str, items: dict) -> list[float]:
    """Collect numeric rubric values for each expected item."""
    out: list[float] = []
    for item_key in CATEGORY_ITEMS.get(cat_key, ()):
        item = items.get(item_key)
        if not isinstance(item, dict):
            continue
        num = _decision_to_score_value(item.get("decision"))
        if num is not None:
            out.append(num)
    return out


def _category_score_from_items(cat_key: str, cat_obj: dict) -> int:
    """
    Derive integer ``score`` 1-5 from ``categories[cat_key].items[*].decision``.

    If there is no usable numeric mean, the category is scored ``1``.
    """
    items = cat_obj.get("items")
    numerics = _gather_item_numerics(cat_key, items if isinstance(items, dict) else {})
    if not numerics:
        return 1

    mean_val = sum(numerics) / len(numerics)
    score = max(1, min(5, round(mean_val)))
    return _critical_fail_cap_int(
        cat_key, items if isinstance(items, dict) else {}, score
    )


def normalize_category_scores_from_item_decisions(review_dict: dict) -> None:
    """
    Set each ``categories[*].score`` from item decisions (integers 1-5).

    The LLM category ``score`` field is replaced; missing or unusable item
    data yields ``1``.
    """
    cats = review_dict.get("categories")
    if not isinstance(cats, dict):
        return
    for cat_key in CATEGORY_KEYS:
        cat_obj = cats.get(cat_key)
        if not isinstance(cat_obj, dict):
            continue
        cat_obj["score"] = _category_score_from_items(cat_key, cat_obj)


def _category_score_label(categories: dict, cat_key: str) -> Optional[int]:
    """
    Return stored category score as 1-5, or None.
    """
    obj = categories.get(cat_key)
    if not isinstance(obj, dict):
        return None
    score = obj.get("score")
    if isinstance(score, int):
        if 1 <= score <= 5:
            return score
        return None
    if isinstance(score, str):
        s = score.strip()
        if s.isdigit():
            n = int(s)
            if 1 <= n <= 5:
                return n
    return None


def _read_category_int(categories: dict, cat_key: str) -> int:
    """Default missing or invalid to ``1`` (lowest)."""
    v = _category_score_label(categories, cat_key)
    if v is None:
        return 1
    return max(1, min(5, v))


def _overall_score_numeric_from_category_ints(category_ints: list[int]) -> int:
    """
    Overall 1-5: ``round`` of the average of category scores, clamped to 1-5.
    """
    n = len(category_ints)
    if n == 0:
        return 1
    s = sum(category_ints)
    return max(1, min(5, round(s / n)))


def _overall_rating_from_numeric(score_numeric: int) -> str:
    """Map 1-5 numeric score to overall rating label."""
    numeric_to_rating = {
        1: OverallRating.POOR.value,
        2: OverallRating.MARGINAL.value,
        3: OverallRating.ADEQUATE.value,
        4: OverallRating.GOOD.value,
        5: OverallRating.EXCELLENT.value,
    }
    return numeric_to_rating.get(score_numeric, OverallRating.POOR.value)


def recompute_overall_fields(review_dict: dict) -> None:
    """
    Set overall fields from normalized category scores (integers 1-5 per
    category).

    Headline fields from the LLM are replaced: overall follows the mean of
    the four category scores, rounded, then mapped to ``overall_rating``.
    """
    cats = review_dict.get("categories") or {}
    if not isinstance(cats, dict):
        cats = {}
    ints = [_read_category_int(cats, k) for k in CATEGORY_KEYS]
    score_numeric = _overall_score_numeric_from_category_ints(ints)
    review_dict["overall_score_numeric"] = score_numeric
    review_dict["overall_rating"] = _overall_rating_from_numeric(score_numeric)


def compute_overall_rating_totals(review_dict: dict) -> tuple[str, int, int]:
    """
    Return ``(overall_rating, total_sum_category_scores, n_categories)``.

    ``total_sum_category_scores`` is the sum of 1-5 per category (max ``5 * n``).
    ``n_categories`` is the number of ``CATEGORY_KEYS``.
    """
    cats = review_dict.get("categories")
    if not isinstance(cats, dict):
        return OverallRating.POOR.value, 0, 0
    ints = [_read_category_int(cats, k) for k in CATEGORY_KEYS]
    n = len(ints)
    total = sum(ints)
    overall_numeric = _overall_score_numeric_from_category_ints(ints)
    rating = _overall_rating_from_numeric(overall_numeric)
    return rating, total, n


def category_scores(review_dict: dict) -> dict[str, Optional[int]]:
    """Return each category score 1-5; ``None`` if missing category object."""
    out: dict[str, Optional[int]] = {}
    cats = review_dict.get("categories")
    if not isinstance(cats, dict):
        for key in CATEGORY_KEYS:
            out[key] = None
        return out
    for key in CATEGORY_KEYS:
        out[key] = _category_score_label(cats, key)
    return out
