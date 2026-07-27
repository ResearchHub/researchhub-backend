from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from feed.serializers import FeedEntrySerializer, ModeratorFeedEntrySerializer
from feed.views.moderator_feed_view import ModeratorFeedViewSet
from paper.tests.helpers import create_paper
from purchase.models import Fundraise, Grant, RscExchangeRate
from purchase.related_models.constants.currency import USD
from purchase.related_models.constants.rsc_exchange_currency import COIN_GECKO
from reputation.models import Escrow
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchJourney
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from researchhub_document.services.journey_service import JourneyService
from user.constants.risk_score_constants import DEFAULT_SCORE
from user.related_models.risk_score_model import RiskScore
from user.tests.helpers import create_hub_editor, create_random_default_user


class PendingModerationFeedTests(TestCase):
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

    def test_pending_grants_return_feed_entries(self):
        # Arrange
        author = create_random_default_user("grant_author")
        RiskScore.objects.create(user=author, score=64)
        grant_post = create_post(created_by=author, document_type=GRANT)
        grant_post.title = "Pending grant title"
        grant_post.renderable_text = "Pending grant body"
        grant_post.save(update_fields=["title", "renderable_text"])
        grant = Grant.objects.create(
            created_by=author,
            unified_document=grant_post.unified_document,
            amount=Decimal("1000.00"),
            currency="USD",
            organization="Org",
            description="desc",
            status=Grant.PENDING,
        )
        open_post = create_post(created_by=author, document_type=GRANT)
        Grant.objects.create(
            created_by=author,
            unified_document=open_post.unified_document,
            amount=Decimal("500.00"),
            currency="USD",
            organization="Org",
            description="open grant",
            status=Grant.OPEN,
        )

        # Act
        response = self.client.get(self.url, {"content_type": "GRANT"})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        item = response.data["results"][0]
        self.assertEqual(item["content_type"], "GRANT")
        self.assertEqual(item["content_object"]["id"], grant.id)
        self.assertEqual(item["content_object"]["status"], Grant.PENDING)
        self.assertEqual(item["content_object"]["post_id"], grant_post.id)
        self.assertEqual(item["content_object"]["title"], grant_post.title)
        self.assertEqual(item["content_object"]["slug"], grant_post.slug)
        self.assertEqual(
            item["content_object"]["renderable_text"], grant_post.renderable_text
        )
        self.assertNotIn("applications", item["content_object"])
        self.assertEqual(item["risk_score"], 64)

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

    def test_rejects_regular_users_from_pending_moderation(self) -> None:
        """Verify regular users cannot access the pending moderation dashboard."""
        # Arrange
        regular = create_random_default_user("regular")
        self.client.force_authenticate(user=regular)

        # Act
        response = self.client.get(self.url, {"content_type": "PREREGISTRATION"})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_allows_hub_editors_to_access_pending_moderation(self) -> None:
        """Verify hub editors can access the pending moderation dashboard."""
        # Arrange
        editor, _ = create_hub_editor("pending_moderation_editor", "Editor Hub")
        self.client.force_authenticate(user=editor)

        # Act
        response = self.client.get(self.url, {"content_type": "PREREGISTRATION"})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)


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


class RegisteredReportCandidateFeedTests(TestCase):
    def setUp(self) -> None:
        """Create a moderator client for registered report candidate requests."""
        self.moderator = create_random_default_user(
            "candidate_moderator",
            moderator=True,
        )
        self.author = create_random_default_user("candidate_author")
        self.client = APIClient()
        self.client.force_authenticate(user=self.moderator)
        self.url = reverse("moderator_feed-registered-report-candidates")
        self.journey_service = JourneyService()
        RscExchangeRate.objects.create(
            price_source=COIN_GECKO,
            rate=3.0,
            real_rate=3.0,
            target_currency=USD,
        )

    def test_returns_only_funded_completed_proposals_without_reports(self) -> None:
        """Verify the dashboard only returns actionable registered report proposals."""
        # Arrange
        candidate = self._create_proposal("candidate")
        self._create_completed_fundraise(candidate, Decimal(100))
        self.journey_service.ensure_approved_preregistration_has_journey(candidate)
        unfunded = self._create_proposal("unfunded")
        self._create_completed_fundraise(
            unfunded,
            Decimal(0),
        )
        self.journey_service.ensure_approved_preregistration_has_journey(unfunded)
        open_proposal = self._create_proposal("open")
        self._create_fundraise(
            open_proposal,
            Fundraise.OPEN,
            Decimal(100),
        )
        self.journey_service.ensure_approved_preregistration_has_journey(open_proposal)
        reported = self._create_proposal("reported")
        self._create_completed_fundraise(reported, Decimal(100))
        journey = self.journey_service.ensure_approved_preregistration_has_journey(
            reported
        )
        report = create_post(
            created_by=self.author,
            document_type=REGISTERED_REPORT,
            title="Registered report",
        )
        self.journey_service.attach_stage(journey, report)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {item["content_object"]["id"] for item in response.data["results"]},
            {candidate.id},
        )

    def test_excludes_funded_proposals_without_matching_journeys(self) -> None:
        """Verify candidates require matching post and journey relationships."""
        # Arrange
        missing_journey = self._create_proposal("missing journey")
        self._create_completed_fundraise(missing_journey, Decimal(100))

        one_way_journey = self._create_proposal("one-way journey")
        self._create_completed_fundraise(one_way_journey, Decimal(100))
        ResearchJourney.objects.create(preregistration_post=one_way_journey)

        mismatched_journey = self._create_proposal("mismatched journey")
        self._create_completed_fundraise(mismatched_journey, Decimal(100))
        other_proposal = self._create_proposal("other proposal")
        other_journey = self.journey_service.get_or_create_for_preregistration(
            other_proposal
        )
        mismatched_journey.journey = other_journey
        mismatched_journey.save(update_fields=["journey"])

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"], [])

    def test_rejects_regular_users(self) -> None:
        """Verify regular users cannot view registered report candidates."""
        # Arrange
        self.client.force_authenticate(user=self.author)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_allows_hub_editors_to_view_registered_report_candidates(self) -> None:
        """Verify hub editors can view registered report candidates."""
        # Arrange
        editor, _ = create_hub_editor("candidate_editor", "Candidate Editor Hub")
        self.client.force_authenticate(user=editor)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def _create_proposal(self, title: str) -> ResearchhubPost:
        """Create an approved proposal owned by the test author."""
        return create_post(
            created_by=self.author,
            document_type=PREREGISTRATION,
            title=title,
        )

    def _create_completed_fundraise(
        self, proposal: ResearchhubPost, amount: Decimal
    ) -> Fundraise:
        """Create a completed fundraise for a proposal."""
        return self._create_fundraise(proposal, Fundraise.COMPLETED, amount)

    def _create_fundraise(
        self,
        proposal: ResearchhubPost,
        status_value: str,
        amount: Decimal,
    ) -> Fundraise:
        """Create a fundraise with the requested status and escrow balance."""
        fundraise = Fundraise.objects.create(
            created_by=proposal.created_by,
            unified_document=proposal.unified_document,
            status=status_value,
        )
        fundraise.escrow = Escrow.objects.create(
            created_by=proposal.created_by,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=fundraise.id,
            hold_type=Escrow.FUNDRAISE,
            amount_holding=amount,
        )
        fundraise.save(update_fields=["escrow"])
        return fundraise


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
