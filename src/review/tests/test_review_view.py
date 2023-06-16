from unittest import skip

from rest_framework.test import APITestCase

from discussion.tests.helpers import create_paper
from user.tests.helpers import create_random_authenticated_user


class ReviewViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("discussion_views")
        self.paper = create_paper(uploaded_by=self.user)

    def test_create_review(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            f"/api/researchhub_unified_document/{self.paper.unified_document.id}/review/",
            {
                "score": 7,
                "content_type": "rhcommentmodel",
                "object_id": 1111,
            },
        )

        self.assertEqual(response.data["score"], 7)

    def test_update_review(self):
        self.client.force_authenticate(self.user)

        create_response = self.client.post(
            f"/api/researchhub_unified_document/{self.paper.unified_document.id}/review/",
            {
                "score": 7,
            },
        )

        id = create_response.data["id"]
        response = self.client.put(
            f"/api/researchhub_unified_document/{self.paper.unified_document.id}/review/{id}/",
            {
                "score": 4,
            },
        )

        self.assertEqual(response.data["score"], 4)
