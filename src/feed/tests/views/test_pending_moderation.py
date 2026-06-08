from django.urls import reverse
from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from feed.serializers import FeedEntrySerializer
from feed.views.feed_view import FeedViewSet
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.constants.risk_score_constants import DEFAULT_SCORE
from user.related_models.risk_score_model import RiskScore
from user.tests.helpers import create_random_default_user
from utils.test_helpers import AWSMockTestCase


class PendingModerationRiskScoreTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.moderator = create_random_default_user("mod", moderator=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.moderator)
        self.url = reverse("feed-pending-moderation")

    def _pending_preregistration(self, author):
        post = create_post(created_by=author, document_type=PREREGISTRATION)
        post.status = ResearchhubPost.PENDING
        post.save(update_fields=["status"])
        return post

    def test_pending_items_include_risk_score_for_moderator(self):
        # Arrange
        scored_author = create_random_default_user("scored")
        RiskScore.objects.create(user=scored_author, score=42)
        default_author = create_random_default_user("default")
        scored_post = self._pending_preregistration(scored_author)
        default_post = self._pending_preregistration(default_author)

        # Act
        response = self.client.get(self.url, {"content_type": "PREREGISTRATION"})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        score_by_post = {
            item["content_object"]["id"]: item["risk_score"]
            for item in response.data["results"]
        }
        self.assertEqual(score_by_post[scored_post.id], 42)
        self.assertEqual(score_by_post[default_post.id], DEFAULT_SCORE)

    def test_risk_score_helper_uses_single_query(self):
        # Arrange: three authors; an N+1 would issue one query per author.
        authors = [create_random_default_user(f"author_{i}") for i in range(3)]
        RiskScore.objects.create(user=authors[0], score=10)
        RiskScore.objects.create(user=authors[1], score=20)

        # Act
        with self.assertNumQueries(1):
            scores = FeedViewSet._risk_score_by_user_id(authors)

        # Assert: scored authors mapped; unscored author falls back at read time.
        self.assertEqual(scores[authors[0].id], 10)
        self.assertEqual(scores[authors[1].id], 20)
        self.assertNotIn(authors[2].id, scores)

    def test_non_moderator_cannot_access_pending_moderation(self):
        # Arrange
        regular = create_random_default_user("regular")
        self.client.force_authenticate(user=regular)

        # Act
        response = self.client.get(self.url, {"content_type": "PREREGISTRATION"})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class FeedEntryRiskScoreFieldTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()

    def _serializer(self, user, **context):
        request = Request(self.factory.get("/"))
        request.user = user
        return FeedEntrySerializer(context={"request": request, **context})

    def test_field_dropped_without_opt_in(self):
        moderator = create_random_default_user("mod_no_flag", moderator=True)
        serializer = self._serializer(moderator)
        self.assertNotIn("risk_score", serializer.fields)

    def test_field_present_for_moderator_with_opt_in(self):
        moderator = create_random_default_user("mod_flag", moderator=True)
        serializer = self._serializer(moderator, include_risk_score=True)
        self.assertIn("risk_score", serializer.fields)

    def test_field_dropped_for_non_moderator_with_opt_in(self):
        regular = create_random_default_user("regular_flag")
        serializer = self._serializer(regular, include_risk_score=True)
        self.assertNotIn("risk_score", serializer.fields)
