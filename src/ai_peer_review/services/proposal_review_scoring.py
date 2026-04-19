import json
import re
from typing import Optional

from ai_peer_review.constants import (
    CATEGORY_ITEMS,
    CATEGORY_KEYS,
    CRITICAL_FAIL_ITEMS,
    OPTIONAL_CATEGORIES,
)
from ai_peer_review.models import OverallRating

# Category label -> points for overall rollup.
SCORE_MAP = {"High": 3, "Medium": 2, "Low": 1}

_OVERALL_EXCELLENT_FRACTION = 18 / 21
_OVERALL_GOOD_FRACTION = 14 / 21


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


def _decision_to_numeric(decision: object) -> Optional[float]:
    """Map one item ``decision`` to a rubric value for averaging; ``N/A`` and unknown return ``None``."""
    if not isinstance(decision, str):
        return None
    key = decision.strip().lower()
    if key == "n/a":
        return None
    if key == "yes":
        return 1.0
    if key == "partial":
        return 0.5
    if key == "no":
        return 0.0
    return None


def _label_from_mean(mean_value: float) -> str:
    """Map mean of yes/partial/no numerics to High / Medium / Low (prompt thresholds)."""
    if mean_value >= 0.75:
        return "High"
    if mean_value >= 0.40:
        return "Medium"
    return "Low"


def _optional_category_all_items_na(cat_key: str, items: dict) -> bool:
    """True when every expected item exists and its ``decision`` is ``N/A`` (optional categories only)."""
    if cat_key not in OPTIONAL_CATEGORIES:
        return False
    expected = CATEGORY_ITEMS.get(cat_key, ())
    if not expected:
        return False
    for item_key in expected:
        item = items.get(item_key)
        if not isinstance(item, dict):
            return False
        raw = item.get("decision")
        if not isinstance(raw, str) or raw.strip().lower() != "n/a":
            return False
    return True


def _critical_fail_cap(cat_key: str, items: dict, label: str) -> str:
    """If label is High and any critical item is ``No``, cap to Medium (sync with prompt)."""
    if label != "High":
        return label
    for ckey, ikey in CRITICAL_FAIL_ITEMS:
        if ckey != cat_key:
            continue
        item = items.get(ikey)
        if not isinstance(item, dict):
            continue
        raw = item.get("decision")
        if isinstance(raw, str) and raw.strip().lower() == "no":
            return "Medium"
    return label


def _gather_item_numerics(cat_key: str, items: dict) -> list[float]:
    """Collect numeric rubric values for each expected item (skips ``N/A`` and unusable decisions)."""
    out: list[float] = []
    for item_key in CATEGORY_ITEMS.get(cat_key, ()):
        item = items.get(item_key)
        if not isinstance(item, dict):
            continue
        num = _decision_to_numeric(item.get("decision"))
        if num is not None:
            out.append(num)
    return out


def _category_score_from_items(cat_key: str, cat_obj: dict) -> str:
    """
    Derive ``score`` from ``categories[cat_key].items[*].decision``.

    Optional categories wholly ``N/A`` become category ``N/A``. If there is no usable
    numeric mean (missing ``items``, missing keys, or no Yes/Partial/No values), the
    category is scored ``Low``.
    """
    items = cat_obj.get("items")
    if _optional_category_all_items_na(
        cat_key, items if isinstance(items, dict) else {}
    ):
        return "N/A"

    numerics = _gather_item_numerics(cat_key, items if isinstance(items, dict) else {})
    if not numerics:
        return "Low"

    mean_val = sum(numerics) / len(numerics)
    label = _label_from_mean(mean_val)
    label = _critical_fail_cap(cat_key, items if isinstance(items, dict) else {}, label)
    return label


def normalize_category_scores_from_item_decisions(review_dict: dict) -> None:
    """
    Set each ``categories[*].score`` from ``categories[*].items[*].decision`` (Yes / Partial / No / N/A).

    Rationales and justifications are left unchanged. The LLM category ``score`` string is
    not used; missing or unusable item data yields ``Low`` (except optional all-``N/A``).
    """
    cats = review_dict.get("categories")
    if not isinstance(cats, dict):
        return
    for cat_key in CATEGORY_KEYS:
        cat_obj = cats.get(cat_key)
        if not isinstance(cat_obj, dict):
            continue
        cat_obj["score"] = _category_score_from_items(cat_key, cat_obj)


def _category_score_label(categories: dict, cat_key: str) -> Optional[str]:
    obj = categories.get(cat_key)
    if not isinstance(obj, dict):
        return None
    score = obj.get("score")
    if score in ("High", "Medium", "Low", "N/A"):
        return score
    return None


def _overall_rating_from_category_labels(labels: list[str]) -> str:
    """
    Map category labels to ``excellent`` / ``good`` / ``poor``.

    Sum points ``T`` (High=3, Medium=2, Low=1); categories with ``N/A`` are skipped.
    With all seven contributing, ``T`` is out of 21: excellent if ``T >= 18``, good if
    ``T >= 14`` (and not excellent), else poor. For fewer contributors, the same
    ``18/21`` and ``14/21`` fractions apply to ``3 * n``.
    """
    points: list[int] = []
    for lab in labels:
        if lab in SCORE_MAP:
            points.append(SCORE_MAP[lab])
    n = len(points)
    if n == 0:
        return OverallRating.POOR.value
    total = sum(points)
    max_points = 3 * n
    if total >= _OVERALL_EXCELLENT_FRACTION * max_points:
        return OverallRating.EXCELLENT.value
    if total >= _OVERALL_GOOD_FRACTION * max_points:
        return OverallRating.GOOD.value
    return OverallRating.POOR.value


def _overall_score_numeric_from_rating(rating: str) -> int:
    """Single 1-3 display/sort field aligned with coarse ``OverallRating``."""
    if rating == OverallRating.EXCELLENT.value:
        return 3
    if rating == OverallRating.GOOD.value:
        return 2
    return 1


def recompute_overall_fields(review_dict: dict) -> None:
    """
    Set ``overall_rating`` and ``overall_score_numeric`` from normalized category scores.

    Headline fields from the LLM are replaced: stored overall values follow the same
    deterministic rubric as category ``score`` labels (see
    :func:`normalize_category_scores_from_item_decisions`).
    """
    labels = [
        _category_score_label(review_dict.get("categories") or {}, k) or "Low"
        for k in CATEGORY_KEYS
    ]
    rating = _overall_rating_from_category_labels(labels)
    review_dict["overall_rating"] = rating
    review_dict["overall_score_numeric"] = _overall_score_numeric_from_rating(rating)


def compute_overall_rating_totals(review_dict: dict) -> tuple[str, int, int]:
    """
    Return ``(overall_rating, total_points, n_contributing)`` after category normalization.

    ``total_points`` sums 1-3 points per contributing category.
    ``n_contributing`` is the count of categories that contributed to that sum.
    """
    cats = review_dict.get("categories")
    if not isinstance(cats, dict):
        return OverallRating.POOR.value, 0, 0
    labels = [_category_score_label(cats, k) or "Low" for k in CATEGORY_KEYS]
    contributing = [lab for lab in labels if lab in SCORE_MAP]
    total = sum(SCORE_MAP[lab] for lab in contributing)
    n = len(contributing)
    rating = _overall_rating_from_category_labels(labels)
    return rating, total, n


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
