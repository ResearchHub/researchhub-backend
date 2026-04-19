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
        d = parse_json_response('{"categories": {"methods_rigor": {"score": "High"}}}')
        self.assertEqual(d["categories"]["methods_rigor"]["score"], "High")

    def test_parse_json_response_code_fence(self):
        raw = 'Here is JSON:\n```json\n{"a": 1}\n```'
        d = parse_json_response(raw)
        self.assertEqual(d["a"], 1)

    def test_parse_json_response_embedded_braces(self):
        d = parse_json_response(
            'noise {"categories": {"methods_rigor": {"score": "Low"}}} tail'
        )
        self.assertEqual(d["categories"]["methods_rigor"]["score"], "Low")

    def test_parse_json_response_invalid_raises(self):
        with self.assertRaises(ValueError):
            parse_json_response("no json here")

    def test_normalize_no_items_yields_low_ignores_headline(self):
        review = {
            "categories": {"methods_rigor": _cat("medium")},
        }
        normalize_category_scores_from_item_decisions(review)
        self.assertEqual(review["categories"]["methods_rigor"]["score"], "Low")

    def test_normalize_na_headline_optional_low_without_all_item_na(self):
        review = {
            "categories": {
                "methods_rigor": _cat("N/A"),
                "statistical_analysis_plan": _cat("n/a"),
            },
        }
        normalize_category_scores_from_item_decisions(review)
        self.assertEqual(review["categories"]["methods_rigor"]["score"], "Low")
        self.assertEqual(
            review["categories"]["statistical_analysis_plan"]["score"],
            "Low",
        )

    def test_normalize_optional_all_items_na_is_category_na(self):
        sap_keys = CATEGORY_ITEMS["statistical_analysis_plan"]
        items = _items_uniform(sap_keys, "N/A")
        review = {
            "categories": {
                "statistical_analysis_plan": {
                    "score": "High",
                    "rationale": "R",
                    "items": items,
                },
            },
        }
        normalize_category_scores_from_item_decisions(review)
        self.assertEqual(
            review["categories"]["statistical_analysis_plan"]["score"],
            "N/A",
        )

    def test_normalize_derived_score_overrides_contradictory_headline(self):
        keys = CATEGORY_ITEMS["funding_opportunity_fit"]
        review = {
            "categories": {
                "funding_opportunity_fit": {
                    "score": "High",
                    "rationale": "R",
                    "items": _items_uniform(keys, "Partial"),
                },
            },
        }
        normalize_category_scores_from_item_decisions(review)
        self.assertEqual(
            review["categories"]["funding_opportunity_fit"]["score"],
            "Medium",
        )

    def test_critical_fail_caps_high_to_medium(self):
        keys = CATEGORY_ITEMS["methods_rigor"]
        items = {k: {"decision": "Yes", "justification": "J"} for k in keys}
        items["methods_detail"] = {"decision": "No", "justification": "J"}
        review = {
            "categories": {
                "methods_rigor": {
                    "score": "High",
                    "rationale": "R",
                    "items": items,
                },
            },
        }
        normalize_category_scores_from_item_decisions(review)
        self.assertEqual(review["categories"]["methods_rigor"]["score"], "Medium")

    def test_recompute_derives_overall_from_categories_not_llm(self):
        review = {
            "overall_rating": "poor",
            "overall_score_numeric": 1,
            "categories": _all_categories_uniform_item_decision("Yes", headline="Low"),
        }
        normalize_category_scores_from_item_decisions(review)
        recompute_overall_fields(review)
        self.assertEqual(review["overall_rating"], OverallRating.EXCELLENT.value)
        self.assertEqual(review["overall_score_numeric"], 3)

    def test_recompute_missing_overall_rating_filled_from_categories(self):
        review = {
            "categories": _all_categories_uniform_item_decision("Yes"),
        }
        normalize_category_scores_from_item_decisions(review)
        recompute_overall_fields(review)
        self.assertEqual(review["overall_rating"], OverallRating.EXCELLENT.value)
        self.assertEqual(review["overall_score_numeric"], 3)

    def test_recompute_invalid_llm_overall_replaced_by_derived(self):
        review = {
            "overall_rating": "maybe",
            "overall_score_numeric": 99,
            "categories": _all_categories_uniform_item_decision("Yes"),
        }
        normalize_category_scores_from_item_decisions(review)
        recompute_overall_fields(review)
        self.assertEqual(review["overall_rating"], OverallRating.EXCELLENT.value)
        self.assertEqual(review["overall_score_numeric"], 3)

    def test_recompute_all_partial_seven_categories_is_good(self):
        review = {
            "overall_rating": "poor",
            "overall_score_numeric": 1,
            "categories": _all_categories_uniform_item_decision("Partial"),
        }
        normalize_category_scores_from_item_decisions(review)
        recompute_overall_fields(review)
        self.assertEqual(review["overall_rating"], OverallRating.GOOD.value)
        self.assertEqual(review["overall_score_numeric"], 2)

    def test_category_scores_reads_normalized_labels(self):
        review = {"categories": {"funding_opportunity_fit": _cat("low")}}
        normalize_category_scores_from_item_decisions(review)
        scores = category_scores(review)
        self.assertEqual(scores["funding_opportunity_fit"], "Low")
