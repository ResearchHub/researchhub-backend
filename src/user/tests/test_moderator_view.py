from rest_framework.test import APITestCase

from user.tests.helpers import (
    create_user,
)


class ModeratorTests(APITestCase):
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
