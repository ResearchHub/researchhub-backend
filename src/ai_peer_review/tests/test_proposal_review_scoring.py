from django.test import SimpleTestCase

from ai_peer_review.constants import CATEGORY_KEYS
from ai_peer_review.models import OverallRating
from ai_peer_review.services.proposal_review_scoring import (
    category_scores,
    normalize_scores_from_answers,
    parse_json_response,
    recompute_overall_fields,
)


def _cat(score: str) -> dict:
    return {"score": score, "rationale": "R", "items": {}}


def _all_categories(scores: dict[str, str]) -> dict:
    return {k: _cat(scores.get(k, "High")) for k in CATEGORY_KEYS}


class ProposalReviewScoringTests(SimpleTestCase):
    def test_parse_json_response_plain(self):
        d = parse_json_response(
            '{"categories": {"methods_rigor": {"score": "High"}}}'
        )
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

    def test_normalize_canonicalizes_case(self):
        review = {
            "categories": {"methods_rigor": _cat("medium")},
        }
        normalize_scores_from_answers(review)
        self.assertEqual(review["categories"]["methods_rigor"]["score"], "Medium")

    def test_normalize_na_only_on_optional_category(self):
        review = {
            "categories": {
                "methods_rigor": _cat("N/A"),
                "statistical_analysis_plan": _cat("n/a"),
            },
        }
        normalize_scores_from_answers(review)
        self.assertEqual(review["categories"]["methods_rigor"]["score"], "Low")
        self.assertEqual(
            review["categories"]["statistical_analysis_plan"]["score"], "N/A"
        )

    def test_recompute_trusts_llm_overall_when_valid(self):
        review = {
            "overall_rating": "Excellent",
            "overall_score_numeric": 2.4,
            "categories": _all_categories({k: "High" for k in CATEGORY_KEYS}),
        }
        normalize_scores_from_answers(review)
        recompute_overall_fields(review)
        self.assertEqual(review["overall_rating"], OverallRating.EXCELLENT.value)
        self.assertEqual(review["overall_score_numeric"], 2)

    def test_recompute_missing_overall_rating_stays_none(self):
        review = {
            "categories": _all_categories({k: "High" for k in CATEGORY_KEYS}),
        }
        normalize_scores_from_answers(review)
        recompute_overall_fields(review)
        self.assertIsNone(review["overall_rating"])

    def test_recompute_invalid_overall_rating_becomes_none(self):
        review = {
            "overall_rating": "maybe",
            "overall_score_numeric": 3,
            "categories": _all_categories({}),
        }
        normalize_scores_from_answers(review)
        recompute_overall_fields(review)
        self.assertIsNone(review["overall_rating"])
        self.assertEqual(review["overall_score_numeric"], 3)

    def test_recompute_fallback_numeric_from_categories(self):
        review = {
            "overall_rating": "poor",
            "overall_score_numeric": "not-a-number",
            "categories": _all_categories(
                {k: "Medium" for k in CATEGORY_KEYS},
            ),
        }
        normalize_scores_from_answers(review)
        recompute_overall_fields(review)
        self.assertEqual(review["overall_rating"], OverallRating.POOR.value)
        self.assertEqual(review["overall_score_numeric"], 2)

    def test_category_scores_reads_normalized_labels(self):
        review = {"categories": {"funding_opportunity_fit": _cat("low")}}
        normalize_scores_from_answers(review)
        scores = category_scores(review)
        self.assertEqual(scores["funding_opportunity_fit"], "Low")
