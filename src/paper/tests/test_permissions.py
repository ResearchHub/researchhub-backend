import random

from rest_framework.test import APITestCase

from user.tests.helpers import create_hub_editor, create_random_authenticated_user

from .helpers import create_paper


class PaperPermissionsIntegrationTests(APITestCase):
    def setUp(self):
        self.random_generator = random.Random("paper")
        self.base_url = "/api/paper/"
        self.paper = create_paper()
        self.flag_reason = "Inappropriate"

    def test_can_flag_paper_with_minimum_reputation(self):
        # Arrange
        user = self.create_user_with_reputation(50)

        # Act
        response = self.get_flag_response(user)

        # Assert
        self.assertContains(response, self.flag_reason, status_code=201)

    def test_moderator_can_update_paper(self):
        # Arrange
        moderator = create_random_authenticated_user(
            self.random_generator.random(), moderator=True
        )

        # Act
        response = self.get_patch_response(moderator, self.paper)

        # Assert
        self.assertEqual(response.status_code, 200)

    def test_hub_editor_can_update_paper(self):
        # Arrange
        editor, _ = create_hub_editor(self.random_generator.random(), "Test Hub")

        # Act
        response = self.get_patch_response(editor, self.paper)

        # Assert
        self.assertEqual(response.status_code, 200)

    def test_regular_user_can_not_update_paper(self):
        # Arrange
        user = create_random_authenticated_user(self.random_generator.random())

        # Act
        response = self.get_patch_response(user, self.paper)

        # Assert
        self.assertEqual(response.status_code, 403)

    def test_uploader_can_not_update_own_paper(self):
        # Arrange
        uploader = create_random_authenticated_user(self.random_generator.random())
        paper = create_paper(title="Uploaded Paper", uploaded_by=uploader)

        # Act
        response = self.get_patch_response(uploader, paper)

        # Assert
        self.assertEqual(response.status_code, 403)

    def test_suspended_moderator_can_not_update_paper(self):
        # Arrange
        moderator = create_random_authenticated_user(
            self.random_generator.random(), moderator=True
        )
        moderator.is_suspended = True
        moderator.save()

        # Act
        response = self.get_patch_response(moderator, self.paper)

        # Assert
        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_can_not_update_paper(self):
        # Arrange
        url = self.base_url + f"{self.paper.id}/"

        # Act
        response = self.client.patch(
            url, {"title": "Patched Paper Title"}, format="multipart"
        )

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_regular_user_can_still_read_paper(self):
        # Arrange
        user = create_random_authenticated_user(self.random_generator.random())
        self.client.force_authenticate(user)

        # Act
        response = self.client.get(self.base_url + f"{self.paper.id}/")

        # Assert
        self.assertEqual(response.status_code, 200)

    def test_regular_user_can_remove_own_vote(self):
        # Arrange
        # `delete_user_vote` has no `permission_classes` of its own, so it falls
        # back to the viewset's. It must not be caught by the update gate.
        user = create_random_authenticated_user(self.random_generator.random())
        self.client.force_authenticate(user)
        self.client.post(f"{self.base_url}{self.paper.id}/upvote/", {}, format="json")

        # Act
        response = self.client.delete(f"{self.base_url}{self.paper.id}/user_vote/")

        # Assert
        self.assertEqual(response.status_code, 200)

    def test_can_upvote_paper_with_minimum_reputation(self):
        # Arrange
        user = self.create_user_with_reputation(1)

        # Act
        response = self.get_upvote_response(user)

        # Assert
        self.assertEqual(response.status_code, 201)

    def test_can_downvote_paper_with_minimum_reputation(self):
        # Arrange
        user = self.create_user_with_reputation(25)

        # Act
        response = self.get_downvote_response(user)

        # Assert
        self.assertEqual(response.status_code, 201)

    def create_user_with_reputation(self, reputation):
        unique_value = self.random_generator.random()
        user = create_random_authenticated_user(unique_value)
        user.reputation = reputation
        user.save()
        return user

    def get_patch_response(self, user, paper):
        if paper is None:
            paper = self.paper
        url = self.base_url + f"{paper.id}/"
        data = {"title": "Patched Paper Title"}
        self.client.force_authenticate(user)
        return self.client.patch(url, data, format="multipart")

    def get_flag_response(self, user):
        url = self.base_url + f"{self.paper.id}/flag/"
        data = {"reason": self.flag_reason, "reason_choice": "SPAM"}
        self.client.force_authenticate(user)
        return self.client.post(url, data, format="json")

    def get_upvote_response(self, user):
        url = self.base_url + f"{self.paper.id}/upvote/"
        data = {}
        self.client.force_authenticate(user)
        return self.client.post(url, data, format="json")

    def get_downvote_response(self, user):
        url = self.base_url + f"{self.paper.id}/downvote/"
        data = {}
        self.client.force_authenticate(user)
        return self.client.post(url, data, format="json")
