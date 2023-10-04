from rest_framework.test import APITestCase

from discussion.tests.helpers import create_paper
from prediction_market.tests.helpers import create_prediction_market
from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import (
    get_authenticated_get_response,
    get_authenticated_post_response,
)


class PredictionMarketVotesViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("prediction_market_views")
        self.paper = create_paper(uploaded_by=self.user)
        self.prediction_market = create_prediction_market(self.paper.id)

    def test_create_prediction_market_vote(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/prediction_market_vote/",
            {
                "prediction_market_id": self.prediction_market.id,
                "vote": True,
            },
        )

        self.assertIsNotNone(response.data["id"])
        self.assertEqual(response.data["created_by"]["id"], self.user.id)

    def test_create_prediction_market_vote_no_prediction_market(self):
        self.client.force_authenticate(self.user)
        # create new paper
        paper = create_paper(uploaded_by=self.user)

        response = self.client.post(
            "/api/prediction_market_vote/",
            {
                "paper_id": paper.id,
                "vote": True,
            },
        )

        self.assertIsNotNone(response.data["id"])

    def test_update_prediction_market_vote(self):
        self.client.force_authenticate(self.user)
        # create new paper
        paper = create_paper(uploaded_by=self.user)

        response = self.client.post(
            "/api/prediction_market_vote/",
            {
                "paper_id": paper.id,
                "vote": True,
            },
        )

        self.assertIsNotNone(response.data["id"])

        response = self.client.post(
            "/api/prediction_market_vote/",
            {
                "paper_id": paper.id,
                "vote": False,
            },
        )

        self.assertIsNotNone(response.data["id"])
        self.assertEqual(response.data["vote"], False)

    def test_list_prediction_market_votes(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(
            f"/api/prediction_market_vote/?prediction_market_id={self.prediction_market.id}"
        )

        self.assertEqual(len(response.data), 0)

        self.client.post(
            "/api/prediction_market_vote/",
            {
                "prediction_market_id": self.prediction_market.id,
                "vote": True,
            },
        )

        response = self.client.get(
            f"/api/prediction_market_vote/?prediction_market_id={self.prediction_market.id}"
        )

        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["created_by"]["id"], self.user.id)

    def test_list_prediction_market_votes_for_user(self):
        self.client.force_authenticate(self.user)
        response = get_authenticated_get_response(
            self.user,
            f"/api/prediction_market_vote/?prediction_market_id={self.prediction_market.id}&is_user_vote=true",
        )

        self.assertEqual(len(response.data), 0)

        get_authenticated_post_response(
            self.user,
            "/api/prediction_market_vote/",
            {
                "prediction_market_id": self.prediction_market.id,
                "vote": True,
            },
        )

        response = get_authenticated_get_response(
            self.user,
            f"/api/prediction_market_vote/?prediction_market_id={self.prediction_market.id}&is_user_vote=true",
        )

        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["created_by"]["id"], self.user.id)

        # create another user and vote
        user2 = create_random_authenticated_user("prediction_market_views")
        get_authenticated_post_response(
            user2,
            "/api/prediction_market_vote/",
            {
                "prediction_market_id": self.prediction_market.id,
                "vote": True,
            },
        )

        response = get_authenticated_get_response(
            self.user,
            f"/api/prediction_market_vote/?prediction_market_id={self.prediction_market.id}&is_user_vote=true",
        )

        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["created_by"]["id"], self.user.id)
