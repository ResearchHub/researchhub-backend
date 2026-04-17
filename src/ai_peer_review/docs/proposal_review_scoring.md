# Proposal review: LLM output vs Python scores

## Where the JSON shape lives

The full structure the model should return (dimensions, sub-areas, `score` / `rationale` / `flags`, Yes/No/Partial fields, and narrative blocks) is specified in:

**[`../prompts/proposal_review_system.txt`](../prompts/proposal_review_system.txt)** — see the **JSON STRUCTURE** section.

Rubric **layout** (which dimensions and sub-areas exist, optional blocks) is mirrored in code as **`DIMENSION_SUB_AREAS`** and **`OPTIONAL_SUB_AREAS`** in [`../constants.py`](../constants.py).

## What we still do in Python

The LLM is asked for each sub-area’s **`score`**, **`rationale`**, and **`flags`**, plus the granular answers (**Yes / No / Partial**, sometimes **N/A**).

After parsing the JSON, **`normalize_scores_from_answers`** in [`../services/proposal_review_scoring.py`](../services/proposal_review_scoring.py) **recomputes** sub-area **`score`** and each dimension’s **`overall_score`** from those **answer fields only** (it skips `score`, `rationale`, and `flags` when averaging).

So headline labels are **not** taken on trust from the model’s own `score` / `overall_score` fields for that step: Python applies a fixed mapping (yes/partial/no → numbers), **numeric thresholds** (see below), optional all-**N/A** handling, and **critical-fail caps** so stored rubric scores stay **consistent and reviewable**.

Narrative content (**rationales**, **flags**, editorial sections, issue tables, etc.) is **not** replaced by that function—it stays as the LLM produced it.

### Numeric thresholds (what “thresholds” means in code)

Answers are turned into numbers (`yes` → 1.0, `partial` → 0.5, `no` → 0.0), then averaged per sub-area and per dimension. **`_label_from_mean`** in [`../services/proposal_review_scoring.py`](../services/proposal_review_scoring.py) maps that mean to a label:

| Mean | Label |
|------|--------|
| ≥ 0.75 | High |
| ≥ 0.40 | Medium |
| &lt; 0.40 | Low |

After all five dimensions have an `overall_score`, **`compute_overall_rating`** maps High/Medium/Low to 3/2/1 points, sums them (5–15), then:

| Sum | `OverallRating` |
|-----|-----------------|
| ≥ 13 | excellent |
| ≥ 8 | good |
| &lt; 8 | poor |

Separately, **critical-fail keys** can cap a sub-area from **High → Medium** when a specific question is **`No`** (see `CRITICAL_FAIL_KEYS` in the same module and the prompt’s “Critical fail cap rule”).

### Why normalize at all?

Think of it as a **second pass on the rubric**: we keep the model’s **evidence** (answers + prose), but we **do not rely on its self-graded `score` / `overall_score`** for the stored headline labels. Those are **derived again** from the Yes/No/Partial answers so a human or auditor sees **one clear rule**—not whatever label the model happened to print next to contradictory answers.

### Tiny example (before → after, then what we store)

**From the LLM** (one sub-area; model’s headline `score` disagrees with its answers):

```json
{
  "fundability": {
    "overall_score": "High",
    "overall_rationale": "Strong alignment with stated goals.",
    "scope_alignment": {
      "score": "High",
      "rationale": "Goals are well specified.",
      "flags": [],
      "rfp_goals": "Yes",
      "aims_boundaries": "Partial",
      "target_population": "No"
    }
  }
}
```

**After `normalize_scores_from_answers`** (same JSON, updated in place): sub-area `score` and dimension `overall_score` follow the numeric rule on `rfp_goals` / `aims_boundaries` / `target_population` only.

**In `ProposalReview.result_data`** you typically persist that **post-normalization** blob—so stored **`score` / `overall_score`** match Python’s rubric, while **`rationale`**, **`flags`**, and answer fields still read as the LLM wrote them.
