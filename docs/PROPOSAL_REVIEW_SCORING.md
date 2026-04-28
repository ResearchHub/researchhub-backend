# Proposal review: LLM output vs Python scores

## Where the JSON shape lives

The structure the model should return (top-level narrative fields, `categories[*].score` / `rationale`, and per-item `decision` / `justification`) is specified in:

**[`src/ai_peer_review/prompts/proposal_review_system.txt`](../src/ai_peer_review/prompts/proposal_review_system.txt)** - see the rubric sections and **OUTPUT JSON SHAPE**.

Rubric **layout** (which categories and items exist) is mirrored in code as **`CATEGORY_KEYS`**, **`CATEGORY_ITEMS`**, and **`CRITICAL_FAIL_ITEMS`** in [`src/ai_peer_review/constants.py`](../src/ai_peer_review/constants.py).

## What Python does after parsing

After parsing the JSON (see `parse_json_response` in [`src/ai_peer_review/services/proposal_review_scoring.py`](../src/ai_peer_review/services/proposal_review_scoring.py)), **`normalize_category_scores_from_item_decisions`** sets each category's **`score`** to an **integer 1-5** from item decisions (`Yes` / `Partial` / `No`).

The model's printed category **`score`** is ignored. If there are no usable item decisions for a category, its stored **`score`** is **`1`**.

**`recompute_overall_fields`** then sets **`overall_score_numeric`** (1-5) and **`overall_rating`** from the **average of the four category scores** (rounded, then mapped to the five overall labels). The LLM's top-level overall fields are overwritten for storage consistency.

Narrative content (`rationales`, `justifications`, `overall_summary`, etc.) is not replaced.

### Decision -> value (per item, 1-5 scale)

| Decision | Value averaged within the category |
|----------|-----------------------------------|
| Yes | 5 |
| Partial | 3 |
| No | 1 |

### Category score (1-5)

For each category, the **mean** of the item values is **rounded** to the nearest integer and **clamped** to **1-5** (see `_category_score_from_items` in code). The same 1-5 scale is used for item contributions, category `score`, and overall rollup.

### Critical fail cap

If any of the following item `decision` values is **`No`**, `rigor_and_feasibility` cannot be **5** (cap to **4** if the mean would otherwise yield 5):

- `rigor_and_feasibility.study_design`
- `rigor_and_feasibility.methodology`
- `rigor_and_feasibility.timeline_feasibility`

### Overall rating and `overall_score_numeric`

With four category scores `s1..s4` (each 1-5):

- `overall_score_numeric = round((s1 + s2 + s3 + s4) / 4)` clamped to `[1, 5]`
- `overall_rating` = mapping from 1-5 to `poor` / `marginal` / `adequate` / `good` / `excellent` (see `OverallRating` in code)

### `compute_overall_rating_totals`

Returns `(overall_rating, total_sum_category_scores, n)` where `total_sum_category_scores` is the **sum** of the four 1-5 category scores (max 20) and `n` is 4 when all category keys are present.

---

## Why normalize?

It is a second pass on the rubric: keep the model's evidence (decisions + prose), but derive stored headline `score` and overall fields with one deterministic rule.

### Tiny example (before -> after)

From the LLM (headline disagrees with item decisions):

```json
{
  "categories": {
    "importance_significance_innovation": {
      "score": 5,
      "rationale": "Strong significance narrative.",
      "items": {
        "hypothesis_strength": { "decision": "Partial", "justification": "..." },
        "work_novelty": { "decision": "Partial", "justification": "..." },
        "question_importance": { "decision": "Partial", "justification": "..." },
        "advances_knowledge": { "decision": "Partial", "justification": "..." }
      }
    }
  }
}
```

After `normalize_category_scores_from_item_decisions`: `importance_significance_innovation.score` becomes **3** (all Partial -> mean 3). Rationale and justifications remain unchanged.

After `recompute_overall_fields`: `overall_rating` / `overall_score_numeric` are updated from all four category scores (here, other categories must be present in a full `review_dict` for a meaningful overall).

---

## Call order

1. `parse_json_response` (or equivalent) -> `dict`
2. `normalize_category_scores_from_item_decisions(review_dict)`
3. `recompute_overall_fields(review_dict)`
4. Persist `review_dict` (for example, `ProposalReview.result_data`) and copy denormalized columns as needed.

Optional helper: **`compute_overall_rating_totals(review_dict)`** returns `(overall_rating, total_sum_category_scores, n)` for tests and diagnostics.
