"""Map TypeSafe Score/Choice answers onto existing judge and peer-review shapes.

Eval-only helpers. They do not call the network; they build question maps and
coerce Jev answers into the dicts ``ProposalJudgePanel.score`` /
``proposal_review_scoring`` already consume. Jev does not emit ``gaps`` or item
justifications, so those fields stay empty.
"""

from __future__ import annotations

import statistics
from typing import Any

# Same ids as ``research_ai.services.proposal_draft.judge_panel``.
RUBRIC_CRITERIA = ("c1", "c2", "c3", "c4", "c5", "c6", "c7")

RUBRIC_INSTRUCTIONS = {
    "c1": (
        "Rate criterion c1: a sharp, testable hypothesis paired with a method "
        "that actually tests it, including concrete success criteria."
    ),
    "c2": (
        "Rate criterion c2: scope fundable at the RFP dollar amount and timeline "
        "in the evaluation context."
    ),
    "c3": (
        "Rate criterion c3: obvious fit to what the funder asked for in the "
        "RFP context."
    ),
    "c4": (
        "Rate criterion c4: author credibility tied to the supplied researcher "
        "track record, not claimed titles the profile does not support."
    ),
    "c5": ("Rate criterion c5: a clear case for why the work matters."),
    "c6": (
        "Rate criterion c6: genuine divergence from the seed literature - a real "
        "research question, not a safe recombination of the source papers."
    ),
    "c7": (
        "Rate criterion c7: scientific writing voice. Reward concrete, "
        "evidence-bearing prose; penalize LLM-tell cliches, marketing, "
        "templated transitions, and ornamental abstraction."
    ),
}

# TypeSafe Score levels are 0-indexed; these five strings are 1-5 on the harness.
RUBRIC_SCORE_LEVELS = [
    "Poor: the draft fails this criterion outright.",
    "Weak: major gaps remain on this criterion.",
    "Adequate: usable but clearly incomplete or generic.",
    "Good: fundable on this criterion with only minor issues.",
    "Excellent: genuinely excellent; reserve this for rare drafts.",
]

PAIRWISE_CHOICE_CRITERIA = {
    "A": "Proposal A is the stronger draft overall for this RFP.",
    "B": "Proposal B is the stronger draft overall for this RFP.",
}

ITEM_DECISION_CRITERIA = {
    "yes": "The proposal fully satisfies this review item.",
    "partial": "The proposal only partially satisfies this review item.",
    "no": "The proposal does not satisfy this review item.",
}

ITEM_DECISION_CANONICAL = {
    "yes": "Yes",
    "partial": "Partial",
    "no": "No",
}

PEER_REVIEW_ITEM_INSTRUCTIONS = {
    "novelty": "Does the proposal present meaningful novelty for the target field?",
    "rigor": "Are the claims proportionate to evidence and methodologically rigorous?",
    "reproducibility": (
        "Does the proposal support reproducibility (data, code, or protocol plans)?"
    ),
    "field_impact": (
        "Is the work likely to shift understanding or practice in the target field?"
    ),
    "hypothesis_strength": "Is the central hypothesis clear and compelling?",
    "work_novelty": "Does the proposed work introduce meaningful novelty?",
    "question_importance": "Does the central question matter for the field?",
    "advances_knowledge": "Would the work advance knowledge if executed as written?",
    "study_design": "Is the study design adequate to answer the stated question?",
    "methodology": "Are the methods specific and sufficient for the aims?",
    "timeline_feasibility": "Is the timeline feasible for the stated scope?",
    "team_qualifications": (
        "Do the supplied team/profile facts support that this group can deliver?"
    ),
    "research_environment": (
        "Does the research environment described support the proposed work?"
    ),
    "budget_appropriateness_justification": (
        "Is the budget appropriate and justified for the aims?"
    ),
    "human_or_animal_protections": (
        "Are human or animal protections addressed when the work involves them, "
        "or clearly not applicable in a way the proposal handles?"
    ),
    "resubmission_critiques_addressed": (
        "If this is a resubmission, are prior critiques addressed? If not a "
        "resubmission, is that clear?"
    ),
    "open_science_adherence": (
        "Does the proposal include transparent sharing or open-science plans "
        "where applicable?"
    ),
    "ai_use_disclosed": (
        "Is AI-assisted writing or analysis disclosed when the proposal uses it?"
    ),
    "conflicts_of_interest_disclosed": (
        "Are conflicts of interest disclosed or explicitly stated as none?"
    ),
}


def noul_question(
    instructions: str,
    *,
    true: str | None = None,
    false: str | None = None,
) -> dict[str, Any]:
    """Build a System One Noul question body."""
    question: dict[str, Any] = {"type": "noul", "instructions": instructions}
    if true is not None or false is not None:
        question["criteria"] = {"true": true, "false": false}
    return question


def choice_question(
    instructions: str,
    criteria: dict[str, str | None],
) -> dict[str, Any]:
    """Build a System One Choice question body."""
    return {
        "type": "choice",
        "instructions": instructions,
        "criteria": criteria,
    }


def score_question(instructions: str, criteria: list[str]) -> dict[str, Any]:
    """Build a System One Score question body."""
    return {
        "type": "score",
        "instructions": instructions,
        "criteria": criteria,
    }


def rubric_score_questions() -> dict[str, dict[str, Any]]:
    """One Score question per proposal-draft rubric criterion c1–c7."""
    return {
        cid: score_question(RUBRIC_INSTRUCTIONS[cid], RUBRIC_SCORE_LEVELS)
        for cid in RUBRIC_CRITERIA
    }


def pairwise_choice_questions() -> dict[str, dict[str, Any]]:
    """One Choice question for seed-selection A vs B."""
    return {
        "winner": choice_question(
            "Which single draft is the stronger proposal overall for this RFP? "
            "Weigh the same qualities as rubric c1–c7, including scientific voice.",
            PAIRWISE_CHOICE_CRITERIA,
        )
    }


def peer_review_choice_questions(
    category_items: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    """One Choice question per ``yes``/``partial``/``no`` peer-review item."""
    questions: dict[str, dict[str, Any]] = {}
    for items in category_items.values():
        for item_key in items:
            instructions = PEER_REVIEW_ITEM_INSTRUCTIONS.get(
                item_key,
                f"Does the proposal satisfy review item {item_key}?",
            )
            questions[item_key] = choice_question(instructions, ITEM_DECISION_CRITERIA)
    return questions


def rubric_int_from_score_answer(answer: dict[str, Any]) -> int:
    """Map a 0-indexed five-level TypeSafe Score onto harness ints 1–5."""
    try:
        raw = float(answer.get("score"))
    except (TypeError, ValueError):
        return 1
    return max(1, min(5, round(raw + 1)))


def canonical_item_decision(choice: object) -> str | None:
    """Map a Choice label onto Yes/Partial/No; unknown values are None."""
    if not isinstance(choice, str):
        return None
    return ITEM_DECISION_CANONICAL.get(choice.strip().lower())


def judge_panel_result_from_answers(
    answers: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Coerce c1–c7 Score answers into ``ProposalJudgePanel.score`` shape."""
    scores: dict[str, int] = {}
    confidences: dict[str, float | None] = {}
    for cid in RUBRIC_CRITERIA:
        answer = answers.get(cid) if isinstance(answers.get(cid), dict) else {}
        scores[cid] = rubric_int_from_score_answer(answer)
        conf = answer.get("confidence")
        confidences[cid] = float(conf) if isinstance(conf, (int, float)) else None
    overall = round(statistics.fmean(list(scores.values())), 2)
    return {
        "scores": scores,
        "overall": overall,
        "gaps": [],
        "judges_reporting": 1,
        "judge_errors": [],
        "confidences": confidences,
    }


def pairwise_winner_from_answers(answers: dict[str, dict[str, Any]]) -> str:
    """Return ``A`` or ``B``; missing answers break to ``A`` like the panel."""
    answer = answers.get("winner") if isinstance(answers.get("winner"), dict) else {}
    winner = str(answer.get("choice") or "").strip().upper()
    return "B" if winner == "B" else "A"


def peer_review_dict_from_answers(
    answers: dict[str, dict[str, Any]],
    category_items: dict[str, list[str]],
) -> dict[str, Any]:
    """Build the item-decision tree ``proposal_review_scoring`` aggregates."""
    categories: dict[str, Any] = {}
    for cat_key, items in category_items.items():
        item_map: dict[str, Any] = {}
        for item_key in items:
            answer = (
                answers.get(item_key) if isinstance(answers.get(item_key), dict) else {}
            )
            decision = canonical_item_decision(answer.get("choice"))
            conf = answer.get("confidence")
            item_map[item_key] = {
                "decision": decision or "",
                "justification": "",
                "confidence": float(conf) if isinstance(conf, (int, float)) else None,
                "probabilities": answer.get("probabilities") or {},
            }
        categories[cat_key] = {
            "score": 1,
            "rationale": "",
            "items": item_map,
        }
    return {"categories": categories}
