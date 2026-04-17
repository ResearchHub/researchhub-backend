from django.test import SimpleTestCase

from ai_peer_review.models import OverallRating
from ai_peer_review.services.proposal_review_scoring import (
    compute_overall_rating,
    normalize_scores_from_answers,
    parse_json_response,
)


class ProposalReviewScoringTests(SimpleTestCase):
    def test_parse_json_response_plain(self):
        d = parse_json_response('{"fundability": {"overall_score": "High"}}')
        self.assertEqual(d["fundability"]["overall_score"], "High")

    def test_parse_json_response_code_fence(self):
        raw = 'Here is JSON:\n```json\n{"a": 1}\n```'
        d = parse_json_response(raw)
        self.assertEqual(d["a"], 1)

    def test_compute_overall_rating_excellent(self):
        review = {
            "fundability": {"overall_score": "High"},
            "feasibility": {"overall_score": "High"},
            "novelty": {"overall_score": "High"},
            "impact": {"overall_score": "High"},
            "reproducibility": {"overall_score": "High"},
        }
        rating, total = compute_overall_rating(review)
        self.assertEqual(total, 15)
        self.assertEqual(rating, OverallRating.EXCELLENT.value)

    def test_compute_overall_rating_poor(self):
        review = {
            "fundability": {"overall_score": "Low"},
            "feasibility": {"overall_score": "Low"},
            "novelty": {"overall_score": "Low"},
            "impact": {"overall_score": "Low"},
            "reproducibility": {"overall_score": "Low"},
        }
        rating, total = compute_overall_rating(review)
        self.assertEqual(total, 5)
        self.assertEqual(rating, OverallRating.POOR.value)

    def test_normalize_critical_fail_caps_high(self):
        """Mean from answers is High, but go_no_go_gates No caps stored score to Medium."""
        review = {
            "fundability": {
                "timeline_realism": {
                    "score": "High",
                    "rationale": "As if LLM mislabeled vs answers.",
                    "flags": [],
                    "timeline_realistic": "Yes",
                    "milestones_sequenced": "Yes",
                    "buffers_adequate": "Yes",
                    "go_no_go_gates": "No",
                }
            },
        }
        normalize_scores_from_answers(review)
        tl = review["fundability"]["timeline_realism"]
        self.assertEqual(tl["go_no_go_gates"], "No")
        self.assertEqual(tl["score"], "Medium")

    def test_parse_json_response_embedded_braces(self):
        d = parse_json_response('noise {"fundability": {"overall_score": "Low"}} tail')
        self.assertEqual(d["fundability"]["overall_score"], "Low")

    def test_parse_json_response_invalid_raises(self):
        with self.assertRaises(ValueError):
            parse_json_response("no json here")
