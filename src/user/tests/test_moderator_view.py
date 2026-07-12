from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from user.tests.helpers import (
    create_hub_editor,
    create_user,
)


class ModeratorTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_moderator_can_view_details(self):
        self.user = create_user(
            email="mod@example.com",
            first_name="Moderator",
            last_name="mod",
            moderator=True,
        )

        self.client.force_authenticate(user=self.user)

        url = f"/api/moderator/{self.user.id}/user_details/"
        response = self.client.get(url, {})
        self.assertIn("id", response.data)

    def test_moderator_details_include_risk_score(self):
        # Arrange
        moderator = create_user(email="mod@example.com", moderator=True)
        self.client.force_authenticate(user=moderator)

        # Act
        response = self.client.get(f"/api/moderator/{moderator.id}/user_details/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("risk_score", response.data)

    def test_hub_editor_can_view_details_without_risk_score(self):
        # Arrange
        editor, _ = create_hub_editor("modview_editor", "Editor Hub")
        target = create_user(email="target@example.com")
        self.client.force_authenticate(user=editor)

        # Act
        response = self.client.get(f"/api/moderator/{target.id}/user_details/")

        # Assert: editors keep access to basic moderator info, but not risk score
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("id", response.data)
        self.assertNotIn("risk_score", response.data)

    def test_hub_editor_cannot_view_risk_score_events(self):
        # Arrange
        editor, _ = create_hub_editor("modview_editor_events", "Editor Hub")
        target = create_user(email="target@example.com")
        self.client.force_authenticate(user=editor)

        # Act
        response = self.client.get(f"/api/moderator/{target.id}/risk_score_events/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_moderator_cannot_view_details(self):
        self.user = create_user(
            email="user@example.com",
            first_name="Moderator",
            last_name="user",
            moderator=False,
        )

        self.client.force_authenticate(user=self.user)

        url = f"/api/moderator/{self.user.id}/user_details/"
        response = self.client.get(url, {})
        self.assertNotIn("id", response.data)

    def test_moderator_can_view_risk_score_events(self):
        moderator = create_user(email="mod@example.com", moderator=True)
        self.client.force_authenticate(user=moderator)

        url = f"/api/moderator/{moderator.id}/risk_score_events/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_non_moderator_cannot_view_risk_score_events(self):
        non_moderator = create_user(email="user@example.com", moderator=False)
        self.client.force_authenticate(user=non_moderator)

        url = f"/api/moderator/{non_moderator.id}/risk_score_events/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
