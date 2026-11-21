import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APITestCase

from feed.services.proposal_ranking_service import (
    STATUS_NOT_OPEN,
    STATUS_OPEN,
    ProposalRankingService,
)
from purchase.models import Fundraise, Grant, GrantApplication
from purchase.related_models.constants.currency import USD
from purchase.related_models.constants.rsc_exchange_currency import COIN_GECKO
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.serializers.grant_serializer import DynamicGrantSerializer
from reputation.models import Escrow
from researchhub_comment.constants.rh_comment_content_types import QUILL_EDITOR
from researchhub_comment.constants.rh_comment_thread_types import PEER_REVIEW
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from review.models import Review
from user.tests.helpers import create_random_authenticated_user

NOW = datetime(2026, 11, 20, tzinfo=UTC)


class _Related(list):
    def all(self):
        return self


def _review(score, is_assessed=True, is_removed=False):
    return SimpleNamespace(score=score, is_assessed=is_assessed, is_removed=is_removed)


def _fundraise(rsc=0, status=Fundraise.OPEN):
    return SimpleNamespace(
        status=status,
        escrow=SimpleNamespace(amount_holding=Decimal(rsc), amount_paid=Decimal(0)),
    )


def _application(name, fundraise=None, reviews=(), score=0, created_days_ago=0):
    ud = SimpleNamespace(
        fundraises=_Related([fundraise] if fundraise else []),
        reviews=_Related(reviews),
    )
    post = SimpleNamespace(
        unified_document=ud,
        score=score,
        created_date=NOW - timedelta(days=created_days_ago),
    )
    return SimpleNamespace(name=name, preregistration_post=post)


class ProposalRankingServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = ProposalRankingService()

    def test_review_score_without_reviews_is_zero(self):
        # Arrange / Act
        score = self.service.review_score([])

        # Assert
        self.assertEqual(score, 0.0)

    def test_review_score_averages_assessed_reviews_only(self):
        # Arrange
        reviews = [
            _review(5),
            _review(3),
            _review(1, is_assessed=False),
            _review(1, is_removed=True),
        ]

        # Act
        score = self.service.review_score(reviews)

        # Assert
        self.assertEqual(score, 4.0)

    def test_amount_raised_sums_escrowed_rsc(self):
        # Arrange
        fundraises = [_fundraise(rsc=100), _fundraise(rsc=20)]

        # Act
        raised = self.service.amount_raised(fundraises)

        # Assert
        self.assertEqual(raised, Decimal(120))

    def test_status_bucket(self):
        # Arrange
        open_fundraise = _fundraise()
        completed = _fundraise(status=Fundraise.COMPLETED)

        # Act / Assert
        self.assertEqual(self.service.status_bucket(open_fundraise), STATUS_OPEN)
        self.assertEqual(self.service.status_bucket(completed), STATUS_NOT_OPEN)
        self.assertEqual(self.service.status_bucket(None), STATUS_NOT_OPEN)

    @patch("feed.services.proposal_ranking_service.prefetch_related_objects")
    def test_sort_grant_applications_uses_strict_tiers(self, _prefetch):
        # Arrange
        applications = [
            _application("closed", _fundraise(rsc=10_000, status=Fundraise.COMPLETED)),
            _application("reviewed_two", _fundraise(), [_review(2)]),
            _application("unreviewed", _fundraise(), created_days_ago=1),
            _application("unreviewed_upvoted", _fundraise(), score=10),
            _application(
                "unassessed_five",
                _fundraise(),
                [_review(5, is_assessed=False)],
                created_days_ago=2,
            ),
            _application("reviewed_four", _fundraise(), [_review(4)], score=50),
            _application("raised", _fundraise(rsc=2)),
        ]

        # Act
        ordered = self.service.sort_grant_applications(applications)

        # Assert
        self.assertEqual(
            [a.name for a in ordered],
            [
                "raised",
                "reviewed_four",
                "reviewed_two",
                "unreviewed_upvoted",
                "unreviewed",
                "unassessed_five",
                "closed",
            ],
        )


class ProposalRankingEndpointTests(APITestCase):
    def setUp(self):
        cache.clear()
        RscExchangeRate.objects.create(rate=0.5, real_rate=0.5, price_source=COIN_GECKO)
        self.moderator = create_random_authenticated_user(
            "ranking_moderator", moderator=True
        )
        self.reviewer = create_random_authenticated_user("ranking_reviewer")

        self.grant_post = create_post(
            created_by=self.moderator, document_type=GRANT, title="Ranking RFP"
        )
        self.grant = Grant.objects.create(
            created_by=self.moderator,
            unified_document=self.grant_post.unified_document,
            amount=Decimal("50000.00"),
            currency=USD,
            organization="RHF",
            description="RFP",
            status=Grant.OPEN,
            end_date=datetime.now(UTC) + timedelta(days=30),
        )

        self.closed = self._proposal("closed", rsc=1_000, status=Fundraise.COMPLETED)
        self.rsc_funded = self._proposal("rsc_funded", rsc=20)
        self.reviewed_four = self._proposal("reviewed_four")
        self._review(self.reviewed_four, 4)
        self.reviewed_two = self._proposal("reviewed_two")
        self._review(self.reviewed_two, 2)
        self.upvoted = self._proposal("upvoted")
        ResearchhubPost.objects.filter(id=self.upvoted.id).update(score=10)
        self.unassessed = self._proposal("unassessed")
        self._review(self.unassessed, 5, is_assessed=False)

        # open first; then raised; then review avg; then upvotes; then newest
        self.expected = [
            self.rsc_funded.id,
            self.reviewed_four.id,
            self.reviewed_two.id,
            self.upvoted.id,
            self.unassessed.id,
            self.closed.id,
        ]

    def tearDown(self):
        cache.clear()

    def _proposal(self, title, rsc=0, status=Fundraise.OPEN):
        applicant = create_random_authenticated_user(f"ranking_{title}")
        post = create_post(
            created_by=applicant, document_type=PREREGISTRATION, title=title
        )
        escrow = Escrow.objects.create(
            created_by=applicant,
            amount_holding=rsc,
            hold_type=Escrow.FUNDRAISE,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=post.unified_document_id,
        )
        Fundraise.objects.create(
            created_by=applicant,
            unified_document=post.unified_document,
            escrow=escrow,
            goal_amount=Decimal("10000.00"),
            goal_currency=USD,
            status=status,
        )
        GrantApplication.objects.create(
            grant=self.grant, preregistration_post=post, applicant=applicant
        )
        return post

    def _review(self, post, score, is_assessed=True):
        thread = RhCommentThreadModel.objects.create(
            created_by=self.reviewer,
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=post.id,
            thread_type=PEER_REVIEW,
        )
        comment = RhCommentModel.objects.create(
            created_by=self.reviewer,
            thread=thread,
            comment_type=PEER_REVIEW,
            comment_content_json={"ops": [{"insert": "Review."}]},
            comment_content_type=QUILL_EDITOR,
        )
        Review.objects.create(
            created_by=self.reviewer,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=comment.id,
            unified_document=post.unified_document,
            score=score,
            is_assessed=is_assessed,
        )

    def _funding_feed_ids(self, ordering):
        response = self.client.get(
            reverse("funding_feed-list"),
            {"grant_id": self.grant.id, "ordering": ordering},
        )
        self.assertEqual(response.status_code, 200)
        return [r["content_object"]["id"] for r in response.data["results"]]

    def test_funding_feed_best_with_grant_id_uses_ranking(self):
        # Act
        ids = self._funding_feed_ids("best")

        # Assert
        self.assertEqual(ids, self.expected)

    def test_grant_feed_applications_use_ranking(self):
        # Act
        response = self.client.get("/api/grant_feed/")

        # Assert
        self.assertEqual(response.status_code, 200)
        entry = next(
            e
            for e in response.data["results"]
            if e["content_object"]["id"] == self.grant_post.id
        )
        ids = [
            a["preregistration_post_id"]
            for a in entry["content_object"]["grant"]["applications"]
        ]
        self.assertEqual(ids, self.expected)

    def test_grant_serializer_applications_use_ranking(self):
        # Arrange
        grant = Grant.objects.get(id=self.grant.id)

        # Act
        data = DynamicGrantSerializer(
            grant, context={}, _include_fields=["applications"]
        ).data

        # Assert
        ids = [a["preregistration_post_id"] for a in data["applications"]]
        self.assertEqual(ids, self.expected)
