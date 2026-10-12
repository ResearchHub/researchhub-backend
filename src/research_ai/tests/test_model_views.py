"""API tests for the selectable-model listing."""

from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.services.usage_budget import TierPolicy
from research_ai.views import model_views
from user.tests.helpers import create_random_authenticated_user

URL = "/api/research_ai/models/"


class AvailableModelsViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)

    @override_settings(RESEARCH_AI_GENERATOR_PROVIDER="bedrock")
    def test_retired_bedrock_default_is_omitted_for_an_unlimited_tier(self):
        # Arrange
        self.client.force_authenticate(self.moderator)
        policy = TierPolicy("privileged", None, None, None, None)

        # Act
        with patch.object(model_views, "resolve_ai_tier", return_value=policy):
            response = self.client.get(URL)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertFalse(
            any(model["provider"] == "bedrock" for model in data["models"])
        )
        self.assertEqual(data["default"], "claude_platform:claude-opus-5-5")

    def test_requires_authentication(self):
        # Act
        response = self.client.get(URL)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_default_user_receives_tier_catalog(self):
        # Arrange
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.get(URL)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["default"], "claude_platform:claude-opus-5-5")
        opus, *others = data["models"]
        self.assertTrue(opus["allowed"])
        self.assertEqual([model["allowed"] for model in others], [False] * 5)
        self.assertEqual(opus["capabilities"]["effort"], ["low"])
        self.assertEqual(opus["capabilities"]["thinking"], ["adaptive"])

    def test_lists_models_and_the_default(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get(URL)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["default"], "claude_platform:claude-opus-5-5")
        refs = [model["ref"] for model in data["models"]]
        self.assertEqual(
            refs,
            [
                "claude_platform:claude-opus-5-5",
                "openrouter:openai/gpt-6.1-sol",
                "openrouter:x-ai/grok-4.7",
                "openrouter:meta/muse-spark-1.3",
                "openrouter:moonshotai/kimi-k3",
                "openrouter:xiaomi/mimo-v2.6-pro",
            ],
        )
        for model in data["models"]:
            self.assertEqual(
                sorted(model),
                [
                    "allowed",
                    "capabilities",
                    "credit_rates",
                    "description",
                    "label",
                    "multiplier",
                    "provider",
                    "ref",
                    "vision",
                ],
            )

        opus = next(
            model
            for model in data["models"]
            if model["ref"] == "claude_platform:claude-opus-5-5"
        )
        self.assertIn("low", opus["capabilities"]["effort"])
        self.assertEqual(opus["capabilities"]["thinking"], ["adaptive"])
        self.assertFalse(opus["capabilities"]["temperature"])
        self.assertEqual(opus["multiplier"], "1.00")
        self.assertEqual(opus["credit_rates"]["input_per_million_tokens"], "4000")
        self.assertEqual(
            data["credit_pricing"],
            {
                "multiplier_base_model": "claude_platform:claude-opus-5-5",
                "multiplier_basis": "equal_input_output_tokens",
                "multiplier_is_estimate": True,
            },
        )

    def test_each_model_says_whether_it_accepts_images(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get(URL)

        # Assert
        vision = {model["ref"]: model["vision"] for model in response.json()["models"]}
        self.assertIs(vision["claude_platform:claude-opus-5-5"], True)
