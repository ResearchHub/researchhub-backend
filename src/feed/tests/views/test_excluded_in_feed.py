from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from feed.models import FeedEntry
from hub.models import Hub
from paper.models import Paper
from purchase.models import Fundraise, Grant
from purchase.related_models.constants.currency import USD
from purchase.related_models.constants.rsc_exchange_currency import COIN_GECKO
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.models import Escrow
from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PAPER,
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from researchhub_document.services.journey_service import JourneyService
from user.tests.helpers import create_random_default_user
from user.views.follow_view_mixins import create_follow
from utils.test_helpers import AWSMockTestCase


def _unified_document_ids(response):
    """Collect unified document ids from feed rows."""
    ids = set()
    for item in response.data["results"]:
        doc_id = item.get("unified_document_id")
        if doc_id is None:
            content_object = item.get("content_object") or {}
            doc_id = content_object.get("unified_document_id")
        if doc_id is None:
            related_work = item.get("related_work") or {}
            doc_id = related_work.get("unified_document_id")
        if doc_id is not None:
            ids.add(doc_id)
    return ids


def _content_object_ids(response):
    ids = set()
    for item in response.data["results"]:
        content_object = item.get("content_object") or {}
        content_id = content_object.get("id")
        if content_id is not None:
            ids.add(content_id)
    return ids


class ExcludedInFeedVisibilityTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = APIClient()
        self.user = create_random_default_user("excluded_feed_user")
        self.moderator = create_random_default_user("excluded_feed_mod", moderator=True)
        self.hub, _ = Hub.objects.get_or_create(
            slug="biorxiv", defaults={"name": "bioRxiv"}
        )
        create_follow(self.user, self.hub)
        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        self.post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

        self.visible_paper_doc, self.visible_paper, self.visible_paper_entry = (
            self._create_paper("Visible Paper")
        )
        self.hidden_paper_doc, self.hidden_paper, self.hidden_paper_entry = (
            self._create_paper("Hidden Paper")
        )
        self._set_excluded(self.hidden_paper_doc, True)

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _create_paper(self, title):
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=PAPER
        )
        unified_document.hubs.add(self.hub)
        paper = Paper.objects.create(
            title=title,
            paper_publish_date=timezone.now(),
            uploaded_by=self.user,
            is_public=True,
            is_removed=False,
            unified_document=unified_document,
        )
        entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=paper.id,
            unified_document=unified_document,
            hot_score=50,
            hot_score_v2=50,
            content={},
            metrics={},
            pdf_copyright_allows_display=True,
        )
        entry.hubs.add(self.hub)
        return unified_document, paper, entry

    def _set_excluded(self, unified_document, excluded):
        document_filter = unified_document.document_filter
        if document_filter is None:
            unified_document.refresh_from_db()
            document_filter = unified_document.document_filter
        document_filter.is_excluded_in_feed = excluded
        document_filter.save(update_fields=["is_excluded_in_feed"])
        cache.clear()

    def test_hidden_paper_is_omitted_from_popular_latest_and_following_feeds(self):
        # Arrange
        self.client.force_authenticate(self.user)
        cases = [
            {"feed_view": "popular", "ordering": "hot_score_v2"},
            {"feed_view": "latest"},
            {"feed_view": "following"},
        ]

        # Act / Assert
        for params in cases:
            response = self.client.get(reverse("feed-list"), params)
            self.assertEqual(response.status_code, status.HTTP_200_OK, params)
            ids = _unified_document_ids(response)
            self.assertIn(self.visible_paper_doc.id, ids, params)
            self.assertNotIn(self.hidden_paper_doc.id, ids, params)

    def test_hidden_paper_remains_directly_retrievable(self):
        # Act
        paper_response = self.client.get(f"/api/paper/{self.hidden_paper.id}/")
        metadata_response = self.client.get(
            f"/api/researchhub_unified_document/{self.hidden_paper_doc.id}"
            "/get_document_metadata/"
        )

        # Assert
        self.assertEqual(paper_response.status_code, status.HTTP_200_OK)
        self.assertEqual(paper_response.data["id"], self.hidden_paper.id)
        self.assertEqual(metadata_response.status_code, status.HTTP_200_OK)
        self.assertEqual(metadata_response.data["id"], self.hidden_paper_doc.id)
        self.assertTrue(
            FeedEntry.objects.filter(pk=self.hidden_paper_entry.pk).exists()
        )

    def test_legacy_null_document_filter_stays_visible(self):
        # Arrange
        ResearchhubUnifiedDocument.objects.filter(pk=self.visible_paper_doc.pk).update(
            document_filter=None
        )
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.get(
            reverse("feed-list"), {"feed_view": "popular", "ordering": "hot_score_v2"}
        )

        # Assert
        self.assertIn(self.visible_paper_doc.id, _unified_document_ids(response))

    def test_hidden_document_and_related_activity_disappear_from_activity_feed(self):
        # Arrange
        visible_grant = create_post(
            created_by=self.user, document_type=GRANT, title="Visible Grant"
        )
        hidden_proposal = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Hidden Proposal",
        )
        visible_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.post_content_type,
            object_id=visible_grant.id,
            unified_document=visible_grant.unified_document,
            user=self.user,
            content={},
            metrics={},
        )
        hidden_post_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.post_content_type,
            object_id=hidden_proposal.id,
            unified_document=hidden_proposal.unified_document,
            user=self.user,
            content={},
            metrics={},
        )
        thread = RhCommentThreadModel.objects.create(
            thread_type=GENERIC_COMMENT,
            content_type=self.post_content_type,
            object_id=hidden_proposal.id,
            created_by=self.user,
        )
        comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "A comment"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            thread=thread,
        )
        hidden_comment_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=comment.id,
            unified_document=hidden_proposal.unified_document,
            user=self.user,
            content={},
            metrics={},
        )
        self._set_excluded(hidden_proposal.unified_document, True)

        # Act
        response = self.client.get(reverse("activity_feed-list"))

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in response.data["results"]}
        self.assertIn(visible_entry.id, ids)
        self.assertNotIn(hidden_post_entry.id, ids)
        self.assertNotIn(hidden_comment_entry.id, ids)

        self._set_excluded(hidden_proposal.unified_document, False)
        restored = self.client.get(reverse("activity_feed-list"))
        restored_ids = {item["id"] for item in restored.data["results"]}
        self.assertIn(hidden_post_entry.id, restored_ids)
        self.assertIn(hidden_comment_entry.id, restored_ids)

    def test_hidden_grant_is_omitted_from_grant_feed(self):
        # Arrange
        visible_post = create_post(
            created_by=self.user, document_type=GRANT, title="Visible Grant"
        )
        hidden_post = create_post(
            created_by=self.user, document_type=GRANT, title="Hidden Grant"
        )
        Grant.objects.create(
            created_by=self.user,
            unified_document=visible_post.unified_document,
            amount=Decimal("1000.00"),
            currency=USD,
            organization="NSF",
            description="Visible",
            status=Grant.OPEN,
        )
        Grant.objects.create(
            created_by=self.user,
            unified_document=hidden_post.unified_document,
            amount=Decimal("2000.00"),
            currency=USD,
            organization="NIH",
            description="Hidden",
            status=Grant.OPEN,
        )
        self._set_excluded(hidden_post.unified_document, True)

        # Act
        response = self.client.get("/api/grant_feed/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = _content_object_ids(response)
        self.assertIn(visible_post.id, ids)
        self.assertNotIn(hidden_post.id, ids)

        post_response = self.client.get(f"/api/researchhubpost/{hidden_post.id}/")
        self.assertEqual(post_response.status_code, status.HTTP_200_OK)

    def test_hidden_proposal_is_omitted_from_funding_feed(self):
        # Arrange
        visible = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Visible Proposal",
        )
        hidden = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Hidden Proposal",
        )
        self._set_excluded(hidden.unified_document, True)

        # Act
        response = self.client.get("/api/funding_feed/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = _content_object_ids(response)
        self.assertIn(visible.id, ids)
        self.assertNotIn(hidden.id, ids)

        self._set_excluded(hidden.unified_document, False)
        restored = self.client.get("/api/funding_feed/")
        self.assertIn(hidden.id, _content_object_ids(restored))

    @patch("purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.usd_to_rsc")
    def test_hidden_registered_report_is_omitted_from_journal_v2_feed(
        self, mock_usd_to_rsc
    ):
        # Arrange
        mock_usd_to_rsc.return_value = 100
        RscExchangeRate.objects.create(
            price_source=COIN_GECKO,
            rate=3.0,
            real_rate=3.0,
            target_currency=USD,
        )
        journey_service = JourneyService()
        visible_proposal = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Visible Journal Proposal",
        )
        hidden_proposal = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Hidden Journal Proposal",
        )
        for proposal in (visible_proposal, hidden_proposal):
            escrow = Escrow.objects.create(
                amount_holding=Decimal("100.00"),
                hold_type=Escrow.FUNDRAISE,
                created_by=self.user,
                content_type=ContentType.objects.get_for_model(
                    ResearchhubUnifiedDocument
                ),
                object_id=proposal.unified_document_id,
            )
            Fundraise.objects.create(
                created_by=self.user,
                unified_document=proposal.unified_document,
                escrow=escrow,
                status=Fundraise.COMPLETED,
                goal_amount=Decimal("100.00"),
                goal_currency=USD,
            )
            journey_service.get_or_create_for_preregistration(proposal)
            proposal.refresh_from_db()
            grant_post = create_post(
                created_by=self.user,
                document_type=GRANT,
                title=f"Grant for {proposal.title}",
            )
            proposal.journey.grant_post = grant_post
            proposal.journey.save(update_fields=["grant_post"])

        visible_report = create_post(
            created_by=self.user,
            document_type=REGISTERED_REPORT,
            title="Visible Registered Report",
        )
        hidden_report = create_post(
            created_by=self.user,
            document_type=REGISTERED_REPORT,
            title="Hidden Registered Report",
        )
        journey_service.attach_stage(visible_proposal.journey, visible_report)
        journey_service.attach_stage(hidden_proposal.journey, hidden_report)
        self._set_excluded(hidden_report.unified_document, True)

        # Act
        response = self.client.get("/api/journal_v2_feed/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = _content_object_ids(response)
        self.assertIn(visible_report.id, ids)
        self.assertNotIn(hidden_report.id, ids)

    def test_pending_moderation_queue_is_unchanged(self):
        # Arrange
        pending = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Pending proposal",
        )
        pending.unified_document.status = ResearchhubUnifiedDocument.PENDING
        pending.unified_document.save(update_fields=["status"])
        self._set_excluded(pending.unified_document, True)
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get(
            reverse("moderator_feed-pending-moderation"),
            {"content_type": "PREREGISTRATION"},
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post_ids = [item["content_object"]["id"] for item in response.data["results"]]
        self.assertIn(pending.id, post_ids)
