import json
from unittest import TestCase

import responses

from research_ai.services.message_screening.jev_client import (
    API_URL,
    MODEL,
    DecisionError,
    JevClient,
)

QUESTIONS = {
    "promotional": {"type": "noul", "instructions": "Is this an ad?"},
    "off_purpose": {"type": "noul", "instructions": "Is this unrelated?"},
}


def decision_response(answers, cost=2.2554e-05) -> dict:
    return {
        "model": "typesafe/jev-1.13-20260917",
        "answers": {
            name: {"type": "noul", "noul": value} for name, value in answers.items()
        },
        "usage": {"input_tokens": 537, "output_tokens": 41, "cost": cost},
        "id": "gen-dec-1",
        "provider": "TypeSafe",
    }


class JevClientTests(TestCase):
    def setUp(self):
        self.client = JevClient("test-key")

    @responses.activate
    def test_returns_each_questions_probability_and_the_cost(self):
        # Arrange
        responses.post(
            API_URL,
            json=decision_response({"promotional": 0.99, "off_purpose": 0.97}),
        )

        # Act
        decision = self.client.decide({"message": "Buy keto gummies"}, QUESTIONS)

        # Assert
        self.assertEqual(decision.model, "typesafe/jev-1.13-20260917")
        self.assertEqual(decision.answers, {"promotional": 0.99, "off_purpose": 0.97})
        self.assertEqual(decision.cost_microusd, 23)
        (call,) = responses.calls
        self.assertEqual(call.request.headers["Authorization"], "Bearer test-key")
        body = json.loads(call.request.body)
        self.assertEqual(body["model"], MODEL)
        self.assertEqual(body["state"], {"message": "Buy keto gummies"})
        self.assertEqual(body["questions"], QUESTIONS)
        self.assertEqual(body["provider"], {"zdr": True})

    @responses.activate
    def test_an_error_response_raises(self):
        # Arrange
        responses.post(API_URL, status=429, json={"error": {"code": 429}})

        # Act & Assert
        with self.assertRaises(DecisionError):
            self.client.decide({"message": "Hi"}, QUESTIONS)

    @responses.activate
    def test_a_missing_or_malformed_answer_raises(self):
        for answers in (
            {"promotional": 0.1},
            {"promotional": 0.1, "off_purpose": None},
            {"promotional": 0.1, "off_purpose": True},
            {"promotional": float("nan"), "off_purpose": 0.9},
            {"promotional": float("inf"), "off_purpose": 0.9},
            {"promotional": 1.5, "off_purpose": 0.9},
            {"promotional": -0.1, "off_purpose": 0.9},
        ):
            with self.subTest(answers=answers):
                # Arrange
                responses.post(API_URL, json=decision_response(answers))

                # Act & Assert
                with self.assertRaises(DecisionError):
                    self.client.decide({"message": "Hi"}, QUESTIONS)

    @responses.activate
    def test_an_unreadable_cost_is_left_unset(self):
        # Arrange
        responses.post(
            API_URL,
            json=decision_response({"promotional": 0.1, "off_purpose": 0.1}, cost=None),
        )

        # Act
        decision = self.client.decide({"message": "Hi"}, QUESTIONS)

        # Assert
        self.assertIsNone(decision.cost_microusd)
