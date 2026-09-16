"""Unit tests for the eval-only TypeSafe client (no live API)."""

import json
from unittest.mock import MagicMock

import requests
from django.test import SimpleTestCase, override_settings

from ai_peer_review.constants import CATEGORY_ITEMS
from ai_peer_review.services.proposal_review_scoring import (
    normalize_category_scores_from_item_decisions,
    recompute_overall_fields,
)
from research_ai.services.typesafe_client import TypeSafeClient, TypeSafeError
from research_ai.services.typesafe_eval import (
    RUBRIC_CRITERIA,
    canonical_item_decision,
    judge_panel_result_from_answers,
    noul_question,
    pairwise_choice_questions,
    pairwise_winner_from_answers,
    peer_review_choice_questions,
    peer_review_dict_from_answers,
    rubric_int_from_score_answer,
    rubric_score_questions,
)


class _FakeResponse:
    def __init__(self, status_code, payload, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class TypeSafeClientTests(SimpleTestCase):
    def test_missing_api_key_raises_before_http(self):
        # Arrange
        http_post = MagicMock()
        client = TypeSafeClient(api_key="", http_post=http_post)

        # Act / Assert
        with self.assertRaises(TypeSafeError) as ctx:
            client.evaluate("state", {"q": noul_question("Is this true?")})
        self.assertIn("TYPESAFE_API_KEY", str(ctx.exception))
        http_post.assert_not_called()

    @override_settings(TYPESAFE_API_KEY="sk-from-settings")
    def test_evaluate_posts_systemone_payload_and_parses_noul(self):
        # Arrange
        http_post = MagicMock(
            return_value=_FakeResponse(
                200,
                {
                    "model": "jev-latest",
                    "answers": {"harmless": {"type": "noul", "noul": 0.91}},
                    "usage": {"input_tokens": 40, "output_tokens": 8},
                },
            )
        )
        client = TypeSafeClient(http_post=http_post)
        questions = {
            "harmless": noul_question("Does this mention a cat?"),
        }

        # Act
        result = client.evaluate("The cat sat on the mat.", questions)

        # Assert
        http_post.assert_called_once()
        args, kwargs = http_post.call_args
        self.assertEqual(args[0], "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(kwargs["timeout"], 30.0)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-from-settings")
        self.assertEqual(kwargs["json"]["model"], "jev-latest")
        self.assertEqual(kwargs["json"]["state"], "The cat sat on the mat.")
        self.assertEqual(kwargs["json"]["questions"]["harmless"]["type"], "noul")
        self.assertEqual(result.answers["harmless"]["noul"], 0.91)
        self.assertEqual(result.usage["input_tokens"], 40)
        self.assertGreaterEqual(result.latency_ms, 0)

    def test_http_error_redacts_api_key_from_message(self):
        # Arrange
        secret = "sk-secret-should-not-leak"
        http_post = MagicMock(
            return_value=_FakeResponse(
                401,
                {"error": "bad key"},
                text=f"unauthorized {secret}",
            )
        )
        client = TypeSafeClient(api_key=secret, http_post=http_post)

        # Act / Assert
        with self.assertRaises(TypeSafeError) as ctx:
            client.evaluate("x", {"q": noul_question("Yes or no?")})
        message = str(ctx.exception)
        self.assertNotIn(secret, message)
        self.assertIn("[redacted]", message)
        self.assertIn("HTTP 401", message)

    def test_transport_failure_does_not_chain_request_headers(self):
        # Arrange
        secret = "sk-header-secret"
        http_post = MagicMock(side_effect=requests.ConnectionError("boom"))
        client = TypeSafeClient(api_key=secret, http_post=http_post)

        # Act / Assert
        with self.assertRaises(TypeSafeError) as ctx:
            client.evaluate("x", {"q": noul_question("Yes or no?")})
        self.assertNotIn(secret, str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)


class TypeSafeEvalMappingTests(SimpleTestCase):
    def test_rubric_questions_are_seven_scores(self):
        # Arrange / Act
        questions = rubric_score_questions()

        # Assert
        self.assertEqual(tuple(questions), RUBRIC_CRITERIA)
        for question in questions.values():
            self.assertEqual(question["type"], "score")
            self.assertEqual(len(question["criteria"]), 5)

    def test_score_answer_maps_zero_indexed_levels_to_one_through_five(self):
        # Arrange / Act / Assert
        self.assertEqual(rubric_int_from_score_answer({"score": 0.0}), 1)
        self.assertEqual(rubric_int_from_score_answer({"score": 4.0}), 5)
        self.assertEqual(rubric_int_from_score_answer({"score": 2.4}), 3)
        self.assertEqual(rubric_int_from_score_answer({"score": "x"}), 1)

    def test_judge_panel_shape_matches_harness_keys(self):
        # Arrange: 0-indexed scores 4,3,2,1,0,4,3 -> 5,4,3,2,1,5,4
        answers = {
            "c1": {"type": "score", "score": 4.0, "confidence": 0.9},
            "c2": {"type": "score", "score": 3.0, "confidence": 0.8},
            "c3": {"type": "score", "score": 2.0, "confidence": 0.7},
            "c4": {"type": "score", "score": 1.0, "confidence": 0.6},
            "c5": {"type": "score", "score": 0.0, "confidence": 0.5},
            "c6": {"type": "score", "score": 4.0, "confidence": 0.4},
            "c7": {"type": "score", "score": 3.0, "confidence": 0.3},
        }

        # Act
        result = judge_panel_result_from_answers(answers)

        # Assert: same keys the panel returns, plus eval confidences.
        self.assertEqual(
            result["scores"],
            {"c1": 5, "c2": 4, "c3": 3, "c4": 2, "c5": 1, "c6": 5, "c7": 4},
        )
        self.assertEqual(result["overall"], 3.43)
        self.assertEqual(result["gaps"], [])
        self.assertEqual(result["judges_reporting"], 1)
        self.assertEqual(result["judge_errors"], [])

    def test_pairwise_choice_breaks_to_a_like_the_panel(self):
        # Arrange / Act / Assert
        self.assertEqual(
            pairwise_winner_from_answers({"winner": {"type": "choice", "choice": "B"}}),
            "B",
        )
        self.assertEqual(pairwise_winner_from_answers({}), "A")
        questions = pairwise_choice_questions()
        self.assertEqual(questions["winner"]["type"], "choice")
        self.assertEqual(set(questions["winner"]["criteria"]), {"A", "B"})

    def test_peer_review_choices_feed_existing_aggregators(self):
        # Arrange: every item yes except a critical-fail methodology no.
        answers = {}
        for items in CATEGORY_ITEMS.values():
            for key in items:
                answers[key] = {
                    "type": "choice",
                    "choice": "yes",
                    "confidence": 0.8,
                    "probabilities": {"yes": 0.8, "partial": 0.1, "no": 0.1},
                }
        answers["methodology"] = {
            "type": "choice",
            "choice": "no",
            "confidence": 0.7,
            "probabilities": {"yes": 0.1, "partial": 0.1, "no": 0.8},
        }
        questions = peer_review_choice_questions(CATEGORY_ITEMS)

        # Act
        review = peer_review_dict_from_answers(answers, CATEGORY_ITEMS)
        normalize_category_scores_from_item_decisions(review)
        recompute_overall_fields(review)

        # Assert
        self.assertEqual(len(questions), 19)
        self.assertEqual(canonical_item_decision("yes"), "Yes")
        self.assertEqual(
            review["categories"]["rigor_and_feasibility"]["items"]["methodology"][
                "decision"
            ],
            "No",
        )
        self.assertEqual(review["categories"]["rigor_and_feasibility"]["score"], 4)
        self.assertIn("overall_score_numeric", review)
        self.assertEqual(
            review["categories"]["overall_impact"]["items"]["novelty"]["justification"],
            "",
        )
