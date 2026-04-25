from django.test import SimpleTestCase

from ai_peer_review.constants import CATEGORY_ITEMS, CATEGORY_KEYS
from ai_peer_review.models import OverallRating
from ai_peer_review.services.proposal_review_scoring import (
    category_scores,
    normalize_category_scores_from_item_decisions,
    parse_json_response,
    recompute_overall_fields,
)


def _cat(score: str) -> dict:
    return {"score": score, "rationale": "R", "items": {}}


def _items_uniform(item_keys: list[str], decision: str) -> dict:
    return {k: {"decision": decision, "justification": "J"} for k in item_keys}


def _category_all_decisions(
    cat_key: str,
    decision: str,
    headline: str = "High",
) -> dict:
    keys = CATEGORY_ITEMS[cat_key]
    return {
        "score": headline,
        "rationale": "R",
        "items": _items_uniform(keys, decision),
    }


def _all_categories_uniform_item_decision(
    decision: str,
    headline: str = "High",
) -> dict:
    return {
        k: _category_all_decisions(k, decision, headline=headline)
        for k in CATEGORY_KEYS
    }


class ProposalReviewScoringTests(SimpleTestCase):
    def test_parse_json_response_plain(self):
        d = parse_json_response('{"categories": {"overall_impact": {"score": "High"}}}')
        self.assertEqual(d["categories"]["overall_impact"]["score"], "High")

    def test_parse_json_response_code_fence(self):
        raw = 'Here is JSON:\n```json\n{"a": 1}\n```'
        d = parse_json_response(raw)
        self.assertEqual(d["a"], 1)

    def test_parse_json_response_embedded_braces(self):
        d = parse_json_response(
            'noise {"categories": {"overall_impact": {"score": "Low"}}} tail'
        )
        self.assertEqual(d["categories"]["overall_impact"]["score"], "Low")

    def test_parse_json_response_invalid_raises(self):
        with self.assertRaises(ValueError):
            parse_json_response("no json here")

    def test_normalize_no_items_yields_low_ignores_headline(self):
        review = {
            "categories": {"overall_impact": _cat("medium")},
        }
        normalize_category_scores_from_item_decisions(review)
        self.assertEqual(review["categories"]["overall_impact"]["score"], "Low")

    def test_normalize_additional_review_criteria_is_scored(self):
        review = {
            "categories": {
                "additional_review_criteria": _category_all_decisions(
                    "additional_review_criteria", "No", headline="High"
                ),
            },
        }
        normalize_category_scores_from_item_decisions(review)
        self.assertEqual(
            review["categories"]["additional_review_criteria"]["score"], "Low"
        )

    def test_normalize_derived_score_overrides_contradictory_headline(self):
        keys = CATEGORY_ITEMS["overall_impact"]
        review = {
            "categories": {
                "overall_impact": {
                    "score": "High",
                    "rationale": "R",
                    "items": _items_uniform(keys, "Partial"),
                },
            },
        }
        normalize_category_scores_from_item_decisions(review)
        self.assertEqual(
            review["categories"]["overall_impact"]["score"],
            "Medium",
        )

    def test_critical_fail_caps_high_to_medium(self):
        keys = CATEGORY_ITEMS["rigor_and_feasibility"]
        items = {k: {"decision": "Yes", "justification": "J"} for k in keys}
        items["study_design"] = {"decision": "No", "justification": "J"}
        review = {
            "categories": {
                "rigor_and_feasibility": {
                    "score": "High",
                    "rationale": "R",
                    "items": items,
                },
            },
        }
        normalize_category_scores_from_item_decisions(review)
        self.assertEqual(
            review["categories"]["rigor_and_feasibility"]["score"],
            "Medium",
        )

    def test_recompute_derives_overall_from_all_scored_categories(self):
        review = {
            "overall_rating": "poor",
            "overall_score_numeric": 1,
            "categories": _all_categories_uniform_item_decision("Yes", headline="Low"),
        }
        normalize_category_scores_from_item_decisions(review)
        recompute_overall_fields(review)
        self.assertEqual(review["overall_rating"], OverallRating.EXCELLENT.value)
        self.assertEqual(review["overall_score_numeric"], 5)

    def test_recompute_all_partial_scored_categories_is_adequate(self):
        review = {
            "overall_rating": "poor",
            "overall_score_numeric": 1,
            "categories": _all_categories_uniform_item_decision("Partial"),
        }
        normalize_category_scores_from_item_decisions(review)
        recompute_overall_fields(review)
        self.assertEqual(review["overall_rating"], OverallRating.ADEQUATE.value)
        self.assertEqual(review["overall_score_numeric"], 3)

    def test_category_scores_reads_normalized_labels(self):
        review = {
            "categories": {
                "overall_impact": _cat("low"),
                "additional_review_criteria": _category_all_decisions(
                    "additional_review_criteria", "Yes"
                ),
            }
        }
        normalize_category_scores_from_item_decisions(review)
        scores = category_scores(review)
        self.assertEqual(scores["overall_impact"], "Low")
        self.assertEqual(scores["additional_review_criteria"], "High")
