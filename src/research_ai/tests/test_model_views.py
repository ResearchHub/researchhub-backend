"""API tests for the selectable-model listing."""

from django.test import override_settings
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

    def test_requires_editor_or_moderator(self):
        # Arrange
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.get(URL)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

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
                ["capabilities", "description", "label", "provider", "ref"],
            )

        opus = next(
            model
            for model in data["models"]
            if model["ref"] == "claude_platform:claude-opus-5"
        )
        self.assertIn("low", opus["capabilities"]["effort"])
        self.assertEqual(opus["capabilities"]["thinking"], ["adaptive", "disabled"])
        self.assertFalse(opus["capabilities"]["temperature"])

    @override_settings(
        ANTHROPIC_AWS_WORKSPACE_ID="", AWS_REGION_NAME="", OPENROUTER_API_KEY=""
    )
    def test_lists_models_without_provider_credentials(self):
        # Arrange: keys are configured on the workers that run turns, not on
        # the API process serving this listing.
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get(URL)

        # Assert
        providers = {model["provider"] for model in response.json()["models"]}
        self.assertIn("openrouter", providers)
        self.assertIn("claude_platform", providers)
