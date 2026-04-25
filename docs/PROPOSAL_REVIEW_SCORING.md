# Proposal review: LLM output vs Python scores

## Where the JSON shape lives

The structure the model should return (top-level narrative fields, `categories[*].score` / `rationale`, and per-item `decision` / `justification`) is specified in:

**[`src/ai_peer_review/prompts/proposal_review_system.txt`](../src/ai_peer_review/prompts/proposal_review_system.txt)** - see the rubric sections and **OUTPUT JSON SHAPE**.

Rubric **layout** (which categories and items exist) is mirrored in code as **`CATEGORY_KEYS`**, **`CATEGORY_ITEMS`**, and **`CRITICAL_FAIL_ITEMS`** in [`src/ai_peer_review/constants.py`](../src/ai_peer_review/constants.py).

## What Python does after parsing

After parsing the JSON (see `parse_json_response` in [`src/ai_peer_review/services/proposal_review_scoring.py`](../src/ai_peer_review/services/proposal_review_scoring.py)), **`normalize_category_scores_from_item_decisions`** sets each category's **`score`** from item decisions (`Yes`/`Partial`/`No` -> `High`/`Medium`/`Low`).

The model's printed category **`score`** is ignored. If there are no usable item decisions for a category, its stored **`score`** is **`Low`**.

**`recompute_overall_fields`** then sets **`overall_rating`** and **`overall_score_numeric`** from normalized labels across all four categories. The LLM's top-level overall fields are overwritten for storage consistency.

Narrative content (`rationales`, `justifications`, `overall_summary`, etc.) is not replaced.

### Decision -> numeric (per item)

| Decision | Value used in mean |
|----------|-------------------|
| Yes | 1.0 |
| Partial | 0.5 |
| No | 0.0 |

### Mean -> category label

For each category, the mean is mapped to **`score`**:

| Mean | Label |
|------|--------|
| >= 0.75 | High |
| >= 0.40 | Medium |
| < 0.40 | Low |

### Critical fail cap

If any of the following item `decision` values is **`No`**, `rigor_and_feasibility` cannot be **`High`** (cap at **`Medium`**):

- `rigor_and_feasibility.study_design`
- `rigor_and_feasibility.methodology`
- `rigor_and_feasibility.timeline_feasibility`

### Overall rating (four scored categories)

Each category maps to points:

| Category score | Points |
|----------------|--------|
| Low | 1 |
| Medium | 2 |
| High | 3 |

Let **`T`** be total points and **`n`** be contributing categories. Max points is **`3n`** (for all four categories, max is **12**).

| Condition | `overall_rating` |
|-----------|------------------|
| `T >= (18/21) * 3n` (>= 11 when `n = 4`) | excellent |
| else if `T >= (14/21) * 3n` (>= 8 when `n = 4`) | good |
| else | poor |

When `n = 0`, Python uses `poor`.

### `overall_score_numeric`

A single integer 1-3 for sorting and UI, derived from `overall_rating`:
- excellent -> 3
- good -> 2
- poor -> 1

---

## Why normalize?

It is a second pass on the rubric: keep the model's evidence (decisions + prose), but derive stored headline `score` and overall fields with one deterministic rule.

### Tiny example (before -> after)

From the LLM (headline disagrees with item decisions):

```json
{
  "categories": {
    "importance_significance_innovation": {
      "score": "High",
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

After `normalize_category_scores_from_item_decisions`: `importance_significance_innovation.score` becomes `Medium` (mean 0.5). Rationale and justifications remain unchanged.

After `recompute_overall_fields`: `overall_rating` / `overall_score_numeric` are updated from normalized category scores.

---

## Call order

1. `parse_json_response` (or equivalent) -> `dict`
2. `normalize_category_scores_from_item_decisions(review_dict)`
3. `recompute_overall_fields(review_dict)`
4. Persist `review_dict` (for example, `ProposalReview.result_data`) and copy denormalized columns as needed.

Optional helper: **`compute_overall_rating_totals(review_dict)`** returns `(overall_rating, total_points, n_contributing)` for tests and diagnostics.
