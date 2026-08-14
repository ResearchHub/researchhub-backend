from decimal import Decimal
from typing import Any
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from purchase.models import Fundraise
from purchase.related_models.constants.currency import USD
from purchase.related_models.constants.rsc_exchange_currency import COIN_GECKO
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.models import Escrow
from researchhub_comment.constants.rh_comment_content_types import QUILL_EDITOR
from researchhub_comment.constants.rh_comment_thread_types import PEER_REVIEW
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.services.journey_service import JourneyService
from researchhub_document.services.researchhub_post_author_service import (
    replace_authors,
)
from review.models import Review
from user.tests.helpers import create_random_default_user
from utils.test_helpers import AWSMockTestCase


class JournalV2FeedViewSetTests(AWSMockTestCase):
    def setUp(self) -> None:
        """Create users and a client for journal feed tests."""
        super().setUp()
        self.user = create_random_default_user("journal_v2_owner")
        self.reviewer = create_random_default_user("journal_v2_reviewer")
        self.service = JourneyService()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        RscExchangeRate.objects.create(
            price_source=COIN_GECKO,
            rate=3.0,
            real_rate=3.0,
            target_currency=USD,
        )

    @patch("purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.usd_to_rsc")
    def test_returns_registered_reports_in_author_order(
        self, mock_usd_to_rsc: Any
    ) -> None:
        """Return only registered reports with canonical author order."""
        # Arrange
        mock_usd_to_rsc.return_value = 100
        proposal_with_report = self.create_completed_proposal("Proposal With Report")
        grant_post = self.attach_grant_post_to_journey(proposal_with_report)
        registered_report = self.create_registered_report(proposal_with_report)
        authors = [self.reviewer.author_profile, self.user.author_profile]
        replace_authors(registered_report, authors)
        completed_proposal = self.create_completed_proposal("Completed Proposal")
        self.create_proposal_review(proposal_with_report, score=8)

        ResearchhubPost.objects.filter(id=registered_report.id).update(
            created_date=timezone.now() - timezone.timedelta(days=2)
        )
        ResearchhubPost.objects.filter(id=completed_proposal.id).update(
            created_date=timezone.now()
        )

        # Act
        response = self.client.get("/api/journal_v2_feed/?ordering=newest")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        post_ids = [entry["content_object"]["id"] for entry in results]
        self.assertEqual(post_ids, [registered_report.id])
        self.assertNotIn(proposal_with_report.id, post_ids)
        self.assertNotIn(completed_proposal.id, post_ids)

        report_card = results[0]["content_object"]
        self.assertEqual(report_card["type"], REGISTERED_REPORT)
        self.assertEqual(report_card["journal_state"], "registered_report")
        self.assertEqual(report_card["proposal"]["id"], proposal_with_report.id)
        self.assertEqual(
            [author["id"] for author in report_card["authors"]],
            [author.id for author in authors],
        )
        self.assertNotIn("review_metrics", results[0]["metrics"])
        self.assertEqual(report_card["fundraise"]["status"], Fundraise.COMPLETED)
        self.assertEqual(
            results[0]["post_ids"],
            {
                "grant_post_id": grant_post.id,
                "proposal_post_id": proposal_with_report.id,
            },
        )
        self.assertNotIn("associated_grants", results[0])
        self.assertNotIn("is_nonprofit", results[0])
        self.assertNotIn("nonprofit", results[0])

    @patch("purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.usd_to_rsc")
    def test_list_excludes_reports_without_funded_completed_fundraises(
        self, mock_usd_to_rsc: Any
    ) -> None:
        """Verify reports require funded completed source fundraises."""
        # Arrange
        mock_usd_to_rsc.return_value = 100
        included_proposal = self.create_completed_proposal("Included Proposal")
        included_report = self.create_registered_report(included_proposal)
        unfunded_proposal = create_post(
            title="Unfunded Proposal",
            created_by=self.user,
            document_type=PREREGISTRATION,
        )
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=unfunded_proposal.unified_document,
            status=Fundraise.COMPLETED,
            goal_amount=Decimal("100.00"),
            goal_currency=USD,
        )
        self.service.get_or_create_for_preregistration(unfunded_proposal)
        excluded_report = self.create_registered_report(unfunded_proposal)

        # Act
        response = self.client.get("/api/journal_v2_feed/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post_ids = [entry["content_object"]["id"] for entry in response.data["results"]]
        self.assertIn(included_report.id, post_ids)
        self.assertNotIn(excluded_report.id, post_ids)

    @patch("purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.usd_to_rsc")
    def test_list_redacts_private_source_proposals_from_reports(
        self, mock_usd_to_rsc: Any
    ) -> None:
        """Verify public reports do not expose private source proposal data."""
        # Arrange
        mock_usd_to_rsc.return_value = 100
        private_proposal = self.create_completed_proposal("Private Proposal")
        self.make_proposal_private(private_proposal)
        private_report_proposal = self.create_completed_proposal(
            "Private Report Proposal"
        )
        self.make_proposal_private(private_report_proposal)
        registered_report = self.create_registered_report(private_report_proposal)

        # Act
        response = self.client.get("/api/journal_v2_feed/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post_ids = [entry["content_object"]["id"] for entry in response.data["results"]]
        self.assertNotIn(private_proposal.id, post_ids)
        self.assertNotIn(private_report_proposal.id, post_ids)
        self.assertIn(registered_report.id, post_ids)
        report_entry = next(
            entry
            for entry in response.data["results"]
            if entry["content_object"]["id"] == registered_report.id
        )
        report_card = report_entry["content_object"]
        self.assertIsNone(report_card["proposal"])
        self.assertIsNone(report_card["fundraise"])
        self.assertEqual(report_card["reviews"], [])
        self.assertEqual(report_card["bounties"], [])
        self.assertEqual(
            report_entry["post_ids"],
            {"grant_post_id": None, "proposal_post_id": None},
        )

    @patch("purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.usd_to_rsc")
    def test_list_orders_by_average_peer_review_score(
        self, mock_usd_to_rsc: Any
    ) -> None:
        """Verify journal sorting can use source proposal review averages."""
        # Arrange
        mock_usd_to_rsc.return_value = 100
        lower_scored_proposal = self.create_completed_proposal("Lower Score")
        lower_scored_report = self.create_registered_report(lower_scored_proposal)
        higher_scored_proposal = self.create_completed_proposal("Higher Score")
        higher_scored_report = self.create_registered_report(higher_scored_proposal)
        self.create_proposal_review(lower_scored_proposal, score=3)
        self.create_proposal_review(higher_scored_proposal, score=9)
        ResearchhubPost.objects.filter(id=lower_scored_report.id).update(
            created_date=timezone.now()
        )
        ResearchhubPost.objects.filter(id=higher_scored_report.id).update(
            created_date=timezone.now() - timezone.timedelta(days=2)
        )

        # Act
        response = self.client.get("/api/journal_v2_feed/?ordering=peer_review_score")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post_ids = [entry["content_object"]["id"] for entry in response.data["results"]]
        self.assertLess(
            post_ids.index(higher_scored_report.id),
            post_ids.index(lower_scored_report.id),
        )

    @patch("purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.usd_to_rsc")
    def test_list_ignores_unassessed_peer_reviews_when_sorting(
        self, mock_usd_to_rsc: Any
    ) -> None:
        """Verify unassessed reviews do not affect journal peer review sorting."""
        # Arrange
        mock_usd_to_rsc.return_value = 100
        assessed_proposal = self.create_completed_proposal("Assessed Review")
        assessed_report = self.create_registered_report(assessed_proposal)
        unassessed_proposal = self.create_completed_proposal("Unassessed Review")
        unassessed_report = self.create_registered_report(unassessed_proposal)
        self.create_proposal_review(assessed_proposal, score=3)
        self.create_proposal_review(unassessed_proposal, score=10, is_assessed=False)
        ResearchhubPost.objects.filter(id=assessed_report.id).update(
            created_date=timezone.now() - timezone.timedelta(days=2)
        )
        ResearchhubPost.objects.filter(id=unassessed_report.id).update(
            created_date=timezone.now()
        )

        # Act
        response = self.client.get("/api/journal_v2_feed/?ordering=peer_review_score")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post_ids = [entry["content_object"]["id"] for entry in response.data["results"]]
        self.assertLess(
            post_ids.index(assessed_report.id),
            post_ids.index(unassessed_report.id),
        )

    @patch("purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.usd_to_rsc")
    def test_list_uses_the_completed_source_fundraise(
        self, mock_usd_to_rsc: Any
    ) -> None:
        """Verify journal cards do not select a newer non-completed fundraise."""
        # Arrange
        mock_usd_to_rsc.return_value = 100
        proposal = self.create_completed_proposal("Completed Fundraise Source")
        completed_fundraise = Fundraise.objects.get(
            unified_document=proposal.unified_document,
            status=Fundraise.COMPLETED,
        )
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            status=Fundraise.OPEN,
            goal_amount=Decimal("200.00"),
            goal_currency=USD,
        )
        report = self.create_registered_report(proposal)

        # Act
        response = self.client.get("/api/journal_v2_feed/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        report_entry = next(
            entry
            for entry in response.data["results"]
            if entry["content_object"]["id"] == report.id
        )
        self.assertEqual(
            report_entry["content_object"]["fundraise"]["id"],
            completed_fundraise.id,
        )

    def test_delete_is_not_allowed_for_anonymous_users(self) -> None:
        """Verify the public journal feed cannot delete its backing posts."""
        # Arrange
        proposal = self.create_completed_proposal("Protected Proposal")
        registered_report = self.create_registered_report(proposal)
        self.client.force_authenticate(user=None)

        # Act
        response = self.client.delete(f"/api/journal_v2_feed/{registered_report.id}/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(
            ResearchhubPost.objects.filter(id=registered_report.id).exists()
        )

    def create_completed_proposal(self, title: str) -> ResearchhubPost:
        """Create a proposal with a funded completed fundraise and journey."""
        proposal = create_post(
            title=title,
            created_by=self.user,
            document_type=PREREGISTRATION,
        )
        self.create_completed_fundraise(proposal)
        self.service.get_or_create_for_preregistration(proposal)
        proposal.refresh_from_db()
        return proposal

    def make_proposal_private(self, proposal: ResearchhubPost) -> None:
        """Make a proposal private after it enters the journal."""
        proposal.unified_document.is_public = False
        proposal.unified_document.save(update_fields=["is_public"])

    def create_completed_fundraise(self, proposal: ResearchhubPost) -> Fundraise:
        """Create a completed fundraise for a proposal."""
        escrow = Escrow.objects.create(
            amount_holding=Decimal("100.00"),
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=proposal.unified_document_id,
        )
        return Fundraise.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            escrow=escrow,
            status=Fundraise.COMPLETED,
            goal_amount=Decimal("100.00"),
            goal_currency=USD,
        )

    def attach_grant_post_to_journey(
        self, proposal: ResearchhubPost
    ) -> ResearchhubPost:
        """Attach a grant post to a proposal journey."""
        grant_post = create_post(
            title=f"Grant for {proposal.title}",
            created_by=self.user,
            document_type=GRANT,
        )
        proposal.journey.grant_post = grant_post
        proposal.journey.save(update_fields=["grant_post"])
        return grant_post

    def create_registered_report(self, proposal: ResearchhubPost) -> ResearchhubPost:
        """Create a registered report attached to a proposal journey."""
        report = create_post(
            title=f"Registered Report for {proposal.title}",
            created_by=self.user,
            document_type=REGISTERED_REPORT,
        )
        self.service.attach_stage(proposal.journey, report)
        return report

    def create_proposal_review(
        self, proposal: ResearchhubPost, score: int, is_assessed: bool = True
    ) -> Review:
        """Create a peer review on a proposal."""
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        comment_content_type = ContentType.objects.get_for_model(RhCommentModel)
        thread = RhCommentThreadModel.objects.create(
            created_by=self.reviewer,
            content_type=post_content_type,
            object_id=proposal.id,
            thread_type=PEER_REVIEW,
        )
        comment = RhCommentModel.objects.create(
            created_by=self.reviewer,
            thread=thread,
            comment_type=PEER_REVIEW,
            comment_content_json={"ops": [{"insert": "Strong proposal."}]},
            comment_content_type=QUILL_EDITOR,
        )
        return Review.objects.create(
            created_by=self.reviewer,
            content_type=comment_content_type,
            object_id=comment.id,
            unified_document=proposal.unified_document,
            score=score,
            is_assessed=is_assessed,
        )
