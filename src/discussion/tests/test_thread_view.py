from rest_framework.test import APITestCase

from discussion.models import Thread
from discussion.tests.helpers import create_paper
from review.models.review_model import Review
from user.tests.helpers import create_random_authenticated_user


class ReviewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("discussion_views")
        self.paper = create_paper(uploaded_by=self.user)

    def test_create_discussion_with_review(self):
        self.client.force_authenticate(self.user)
        review_response = self.client.post(
            f"/api/researchhub_unified_document/{self.paper.unified_document.id}/review/",
            {
                "score": 7,
            },
        )

        rev = Review.objects.get(id=review_response.data["id"])
        thread_response = self.client.post(
            f"/api/paper/{self.paper.id}/discussion/?source=researchhub&is_removed=False",
            {
                "plain_text": "review text",
                "paper": self.paper.id,
                "review": rev.id,
                "text": {"ops": [{"insert": "review text"}]},
            },
        )

        self.assertIn("id", thread_response.data["review"])

    def test_discussion_list_includes_review_data(self):
        self.client.force_authenticate(self.user)
        review_response = self.client.post(
            f"/api/researchhub_unified_document/{self.paper.unified_document.id}/review/",
            {
                "score": 7,
            },
        )

        rev = Review.objects.get(id=review_response.data["id"])
        thread_response = self.client.post(
            f"/api/paper/{self.paper.id}/discussion/?source=researchhub&is_removed=False",
            {
                "plain_text": "review text",
                "paper": self.paper.id,
                "review": rev.id,
                "text": {"ops": [{"insert": "review text"}]},
            },
        )

        response = self.client.get(
            f"/api/paper/{self.paper.id}/discussion/?page=1&ordering=-score&source=researchhub&is_removed=False&"
        )

        print(response.data)
        self.assertEqual(
            response.data["results"][0]["review"]["id"],
            review_response.data["id"],
        )
