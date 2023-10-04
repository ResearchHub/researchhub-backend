from rest_framework.test import APITestCase

from discussion.tests.helpers import create_paper
from user.tests.helpers import create_random_authenticated_user


class PredictionMarketViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("discussion_views")
        self.paper = create_paper(uploaded_by=self.user)

    def test_create_prediction_market(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/prediction_market/",
            {
                "paper_id": self.paper.id,
            },
        )

        self.assertIsNotNone(response.data["id"])
        self.assertEqual(response.data["votes"]["total"], 0)
