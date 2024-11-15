from rest_framework import status
from rest_framework.test import APITestCase

from discussion.tests.helpers import create_paper
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from review.models.peer_review_model import PeerReview
from user.tests.helpers import create_random_authenticated_user


class PeerReviewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("moderator1", moderator=True)
        self.reviewer = create_random_authenticated_user("reviewer1")
        self.paper = create_paper(uploaded_by=self.moderator)

    def test_create_peer_review_success(self):
        # Arrange
        self.client.force_authenticate(user=self.moderator)

        # Act
        actual = self.client.post(
            f"/api/paper/{self.paper.id}/peer-review/",
            {
                "paper": self.paper.id,
                "user": self.reviewer.id,
            },
        )

        # Assert
        self.assertEqual(actual.status_code, status.HTTP_201_CREATED)
        peer_review_id = actual.data["id"]
        self.assertGreater(peer_review_id, 0)
        peer_review = PeerReview.objects.filter(id=peer_review_id).first()
        self.assertIsNotNone(peer_review)

    def test_create_peer_review_unauthenticated(self):
        # Act
        actual = self.client.post(
            f"/api/paper/{self.paper.id}/peer-review/",
            {
                "paper": self.paper.id,
                "user": self.reviewer.id,
            },
        )

        # Assert
        self.assertEqual(actual.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_peer_review_invalid_request(self):
        # Arrange
        self.client.force_authenticate(user=self.moderator)

        # Act
        actual = self.client.post(
            f"/api/paper/{self.paper.id}/peer-review/",
            {
                "paper": self.paper.id,
                # User is missing!
            },
        )

        print(actual.data)

        # Assert
        self.assertEqual(actual.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_peer_review_user_paper_conflict(self):
        # Arrange
        self.client.force_authenticate(user=self.moderator)
        body = {
            "paper": self.paper.id,
            "user": self.reviewer.id,
        }

        # Act
        actual = self.client.post(
            f"/api/paper/{self.paper.id}/peer-review/",
            body,
        )
        self.assertEqual(actual.status_code, status.HTTP_201_CREATED)

        # attempt to create the same peer review again
        actual = self.client.post(
            f"/api/paper/{self.paper.id}/peer-review/",
            body,
        )

        # Assert
        self.assertEqual(actual.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_peer_review_success(self):
        # Arrange
        self.client.force_authenticate(user=self.moderator)
        response = self.client.post(
            f"/api/paper/{self.paper.id}/peer-review/",
            {
                "paper": self.paper.id,
                "user": self.reviewer.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        peer_review_id = response.data["id"]

        thread = self._create_comment(self.paper, self.reviewer, "title", "text")

        # Act
        actual = self.client.patch(
            f"/api/paper/{self.paper.id}/peer-review/{peer_review_id}/",
            {
                "id": peer_review_id,
                "comment_thread": thread.id,
                "status": PeerReview.Status.APPROVED,
            },
        )

        # Assert
        self.assertEqual(actual.status_code, status.HTTP_200_OK)
        peer_review = PeerReview.objects.filter(
            paper=self.paper, user=self.reviewer
        ).first()
        self.assertEqual(peer_review.status, PeerReview.Status.APPROVED)

    def test_update_peer_review_unauthenticated(self):
        # Act
        actual = self.client.patch(
            f"/api/paper/{self.paper.id}/peer-review/123/",
            {},
        )

        # Assert
        self.assertEqual(actual.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_update_peer_review_invalid_request(self):
        # Arrange
        self.client.force_authenticate(user=self.moderator)
        response = self.client.post(
            f"/api/paper/{self.paper.id}/peer-review/",
            {
                "paper": self.paper.id,
                "user": self.reviewer.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        peer_review_id = response.data["id"]

        # Act
        actual = self.client.patch(
            f"/api/paper/{self.paper.id}/peer-review/{peer_review_id}/",
            {
                "id": peer_review_id,
                # missing comment_thread and status!
            },
        )

        # Assert
        self.assertEqual(actual.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_peer_reviews_success(self):
        # Arrange
        self.client.force_authenticate(user=self.moderator)
        response = self.client.post(
            f"/api/paper/{self.paper.id}/peer-review/",
            {
                "paper": self.paper.id,
                "user": self.reviewer.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Act
        actual = self.client.get(f"/api/paper/{self.paper.id}/peer-review/")

        # Assert
        self.assertEqual(actual.status_code, status.HTTP_200_OK)
        self.assertEqual(len(actual.data["results"]), 1)

    def _create_comment(self, paper, created_by, title, text, parent=None):
        thread = RhCommentThreadModel.objects.create(
            content_object=paper,
            created_by=created_by,
            updated_by=created_by,
        )
        return thread
