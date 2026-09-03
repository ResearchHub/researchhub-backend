"""API tests for the selectable-model listing."""

from rest_framework import status
from rest_framework.test import APITestCase

from user.tests.helpers import create_random_authenticated_user

URL = "/api/research_ai/models/"


class AvailableModelsViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)

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
        self.assertEqual(
            response.json()["default"],
            "openrouter:deepseek/deepseek-v4-flash-0731",
        )

    def test_lists_models_and_the_default(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get(URL)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["default"], "claude_platform:claude-opus-5")
        refs = [model["ref"] for model in data["models"]]
        self.assertIn("claude_platform:claude-opus-5", refs)
        self.assertIn("openrouter:openai/gpt-5.6-sol", refs)
        for model in data["models"]:
            self.assertEqual(
                sorted(model),
                [
                    "allowed",
                    "capabilities",
                    "description",
                    "label",
                    "multiplier",
                    "provider",
                    "ref",
                ],
            )

        opus = next(
            model
            for model in data["models"]
            if model["ref"] == "claude_platform:claude-opus-5"
        )
        self.assertIn("low", opus["capabilities"]["effort"])
        self.assertEqual(opus["capabilities"]["thinking"], ["adaptive", "disabled"])
        self.assertFalse(opus["capabilities"]["temperature"])
