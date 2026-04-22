# Proposal review: LLM output vs Python scores

## Where the JSON shape lives

The structure the model should return (top-level narrative fields, `categories[*].score` / `rationale`, and per-item `decision` / `justification`) is specified in:

**[`src/ai_peer_review/prompts/proposal_review_system.txt`](../src/ai_peer_review/prompts/proposal_review_system.txt)** — see the rubric sections and **OUTPUT JSON SHAPE**.

Rubric **layout** (which categories and items exist, which categories are optional) is mirrored in code as **`CATEGORY_KEYS`**, **`CATEGORY_ITEMS`**, **`OPTIONAL_CATEGORIES`**, and **`CRITICAL_FAIL_ITEMS`** in [`src/ai_peer_review/constants.py`](../src/ai_peer_review/constants.py).

## What Python does after parsing

After parsing the JSON (see `parse_json_response` in [`src/ai_peer_review/services/proposal_review_scoring.py`](../src/ai_peer_review/services/proposal_review_scoring.py)), **`normalize_category_scores_from_item_decisions`** sets each category’s **`score`** only from **`categories[category].items[item].decision`**. The model’s printed category **`score`** is ignored. If there are no usable item decisions for a category, its stored **`score`** is **`Low`** (except optional categories where every item is **`N/A`**, which become **`N/A`**).

**`recompute_overall_fields`** then sets **`overall_rating`** and **`overall_score_numeric`** from those normalized category labels using the **21-point** overall band (scaled when **`n` < 7**; see below). The LLM’s top-level overall fields are **overwritten** for storage consistency.

Narrative content (**rationales**, **justifications**, **overall_summary**, etc.) is **not** replaced—it stays as the LLM produced it.

### Decision → numeric (per item)

| Decision | Value used in mean |
|----------|-------------------|
| Yes | 1.0 |
| Partial | 0.5 |
| No | 0.0 |
| N/A | omitted from the mean (optional categories only, per prompt) |

### Mean → category label

For each category, the mean is taken over items that contributed a numeric value. It is mapped to **`score`**:

| Mean | Label |
|------|--------|
| ≥ 0.75 | High |
| ≥ 0.40 | Medium |
| &lt; 0.40 | Low |

### Optional all-N/A category

For **`statistical_analysis_plan`**, **`clinical_or_translational_impact`**, and **`societal_and_broader_impact`**: if **every** expected item’s `decision` is **`N/A`**, the category **`score`** is **`N/A`**. That category contributes **no** points to the overall rollup (`n` is reduced).

### Critical fail cap

If any of the following item `decision` values is **`No`**, the owning category **`score`** cannot be **`High`** (cap at **`Medium`** even when the mean would be High). Keys must stay aligned with the prompt and with **`CRITICAL_FAIL_ITEMS`** in `constants.py`:

- `methods_rigor.methods_detail`
- `methods_rigor.controls_defined`
- `statistical_analysis_plan.analysis_present`
- `statistical_analysis_plan.power_analysis`
- `feasibility_and_execution.timeline_milestones`

### Overall rating (seven categories)

Each contributing category (any label except **`N/A`**) maps to points:

| Category score | Points |
|----------------|--------|
| Low | 1 |
| Medium | 2 |
| High | 3 |

Let **`T`** = sum of points and **`n`** = number of contributing categories. The maximum achievable is **`3n`** (seven categories and three points each when **`n = 7`** gives **21**).

| Condition | `overall_rating` |
|-----------|------------------|
| `T` ≥ **`(18/21) × 3n`** (i.e. **≥ 18** when **`n = 7`**) | excellent |
| else if `T` ≥ **`(14/21) × 3n`** (i.e. **≥ 14** when **`n = 7`**) | good |
| else | poor |

Scaling by **`3n`** keeps the same **18/21** and **14/21** fractions when optional whole-category **`N/A`** rows reduce **`n`**.

When **`n` = 0** (e.g. every category **`N/A`**, which should not happen in normal output), Python uses **poor**.

### `overall_score_numeric`

A single integer **1–3** for sorting and UI, derived from **`overall_rating`**: excellent → **3**, good → **2**, poor → **1**. It is **not** taken from the LLM after normalization.

---

## Why normalize?

It is a **second pass on the rubric**: keep the model’s **evidence** (decisions + prose), but derive stored headline **`score`** and overall fields with **one clear rule**—not whatever label the model printed next to contradictory decisions.

### Tiny example (before → after)

**From the LLM** (category headline disagrees with item decisions):

```json
{
  "categories": {
    "funding_opportunity_fit": {
      "score": "High",
      "rationale": "Strong fit narrative.",
      "items": {
        "fit_modality": { "decision": "Partial", "justification": "..." },
        "fit_aims": { "decision": "Partial", "justification": "..." },
        "fit_deliverables": { "decision": "Partial", "justification": "..." },
        "fit_scope": { "decision": "Partial", "justification": "..." }
      }
    }
  }
}
```

**After `normalize_category_scores_from_item_decisions`** (same JSON, in place): `funding_opportunity_fit.score` becomes **`Medium`** (mean 0.5). Rationale and justifications are unchanged.

**After `recompute_overall_fields`**: `overall_rating` / `overall_score_numeric` are updated from **all** categories’ normalized scores, not from the LLM’s prior overall fields.

---

## Call order

1. `parse_json_response` (or equivalent) → `dict`  
2. `normalize_category_scores_from_item_decisions(review_dict)`  
3. `recompute_overall_fields(review_dict)`  
4. Persist `review_dict` (e.g. `ProposalReview.result_data`) and copy denormalized columns as needed.

Optional helper: **`compute_overall_rating_totals(review_dict)`** returns `(overall_rating, total_points, n_contributing)` for tests or diagnostics.
