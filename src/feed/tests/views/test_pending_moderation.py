from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from feed.serializers import FeedEntrySerializer, ModeratorFeedEntrySerializer
from feed.views.moderator_feed_view import ModeratorFeedViewSet
from paper.tests.helpers import create_paper
from purchase.models import Grant
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.constants.risk_score_constants import DEFAULT_SCORE
from user.related_models.risk_score_model import RiskScore
from user.tests.helpers import create_random_default_user


class PendingModerationRiskScoreTests(TestCase):
    def setUp(self):
        self.moderator = create_random_default_user("mod", moderator=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.moderator)
        self.url = reverse("moderator_feed-pending-moderation")

    def _pending_preregistration(self, author):
        post = create_post(created_by=author, document_type=PREREGISTRATION)
        post.unified_document.status = ResearchhubUnifiedDocument.PENDING
        post.unified_document.save(update_fields=["status"])
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
            scores = ModeratorFeedViewSet._risk_score_by_user_id(authors)

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


class PendingModerationCountsTests(TestCase):
    def test_counts_grouped_by_type(self):
        # Arrange
        author = create_random_default_user("counts_author")
        grant_post = create_post(created_by=author, document_type=GRANT)
        Grant.objects.create(
            created_by=author,
            unified_document=grant_post.unified_document,
            amount=Decimal("1000.00"),
            currency="USD",
            organization="Org",
            description="desc",
            status=Grant.PENDING,
        )
        # Two proposals distinguish the two post-backed tabs from each other.
        for document_type in (PREREGISTRATION, PREREGISTRATION, DISCUSSION):
            post = create_post(created_by=author, document_type=document_type)
            post.unified_document.status = ResearchhubUnifiedDocument.PENDING
            post.unified_document.save(update_fields=["status"])
        paper = create_paper(uploaded_by=author)
        paper.unified_document.status = ResearchhubUnifiedDocument.PENDING
        paper.unified_document.save(update_fields=["status"])
        client = APIClient()
        client.force_authenticate(create_random_default_user("mod", moderator=True))

        # Act
        response = client.get(reverse("moderator_feed-pending-moderation-counts"))

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "funding_opportunities": 1,
                "proposals": 2,
                "posts": 1,
                "journal_entries": 1,
            },
        )


class FeedEntryRiskScoreFieldTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def _serializer(self, serializer_class, user):
        request = Request(self.factory.get("/"))
        request.user = user
        return serializer_class(context={"request": request})

    def test_base_serializer_never_exposes_risk_score(self):
        # Arrange
        moderator = create_random_default_user("mod_base", moderator=True)

        # Act
        serializer = self._serializer(FeedEntrySerializer, moderator)

        # Assert
        self.assertNotIn("risk_score", serializer.fields)

    def test_moderator_serializer_exposes_risk_score_for_moderator(self):
        # Arrange
        moderator = create_random_default_user("mod_flag", moderator=True)

        # Act
        serializer = self._serializer(ModeratorFeedEntrySerializer, moderator)

        # Assert
        self.assertIn("risk_score", serializer.fields)

    def test_moderator_serializer_drops_risk_score_for_non_moderator(self):
        # Arrange
        regular = create_random_default_user("regular_flag")

        # Act
        serializer = self._serializer(ModeratorFeedEntrySerializer, regular)

        # Assert
        self.assertNotIn("risk_score", serializer.fields)
