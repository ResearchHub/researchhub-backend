from django.test import SimpleTestCase

from research_ai.constants import OverallRating
from research_ai.services.proposal_review_scoring import (
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
        review = {
            "fundability": {
                "timeline_realism": {
                    "timeline_realistic": "Yes",
                    "milestones_sequenced": "Yes",
                    "buffers_adequate": "Yes",
                    "go_no_go_gates": "No",
                }
            },
            "feasibility": {
                "investigator_expertise": {
                    "publication_record": "Yes",
                    "methods_expertise": "Yes",
                    "comparable_projects": "Yes",
                    "recent_activity": "Yes",
                    "team_composition": "Yes",
                },
                "institutional_capacity": {
                    "core_facilities": "Yes",
                    "specialized_resources": "Yes",
                    "institutional_support": "Yes",
                },
                "track_record": {
                    "score": "N/A",
                    "rationale": "N/A",
                    "prior_grants": "N/A",
                    "h_index_profile": "N/A",
                    "open_science": "N/A",
                    "community_engagement": "N/A",
                    "endorsements": "N/A",
                },
            },
            "novelty": {
                "conceptual_novelty": {
                    "new_hypothesis": "Yes",
                    "challenges_models": "Yes",
                    "distinct_framing": "Yes",
                },
                "methodological_novelty": {
                    "new_methods": "Yes",
                    "combined_methods": "Yes",
                    "new_tools_datasets": "Yes",
                },
                "literature_positioning": {
                    "prior_work_cited": "Yes",
                    "pi_overlap": "Yes",
                    "recent_overlap": "Yes",
                    "concurrent_work": "Yes",
                },
            },
            "impact": {
                "scientific_impact": {
                    "fundamental_understanding": "Yes",
                    "generalizability": "Yes",
                    "new_directions": "Yes",
                },
                "clinical_translational_impact": {
                    "score": "N/A",
                    "rationale": "N/A",
                    "clinical_path": "N/A",
                    "unmet_need": "N/A",
                    "translational_milestones": "N/A",
                },
                "societal_broader_impact": {
                    "societal_challenge": "Yes",
                    "public_communication": "Yes",
                    "commercial_application": "Yes",
                },
                "community_ecosystem_impact": {
                    "score": "N/A",
                    "rationale": "N/A",
                    "public_outputs": "N/A",
                    "pi_reusable_outputs": "N/A",
                    "community_demand": "N/A",
                },
            },
            "reproducibility": {
                "methods_rigor": {
                    "methods_detail": "Yes",
                    "parameters_specified": "Yes",
                    "controls_defined": "Yes",
                    "model_justified": "Yes",
                },
                "statistical_analysis_plan": {
                    "stats_plan": "Yes",
                    "power_analysis": "Yes",
                    "multiple_comparisons": "Yes",
                    "evaluation_metrics": "Yes",
                },
                "data_code_transparency": {
                    "data_sharing_plan": "Yes",
                    "code_sharing_plan": "Yes",
                    "pi_data_history": "Yes",
                    "data_management": "Yes",
                },
                "gold_standard_methodology": {
                    "score": "N/A",
                    "rationale": "N/A",
                    "gold_standard_used": "N/A",
                    "non_standard_justified": "N/A",
                    "justification_compelling": "N/A",
                    "novel_method_validated": "N/A",
                    "literature_support": "N/A",
                    "prior_studies_cited": "N/A",
                    "gold_standard_correctly_applied": "N/A",
                },
                "validation_robustness": {
                    "validation_strategies": "Yes",
                },
            },
        }
        normalize_scores_from_answers(review)
        tl = review["fundability"]["timeline_realism"]
        self.assertEqual(tl["go_no_go_gates"], "No")
        self.assertEqual(tl["score"], "Medium")
