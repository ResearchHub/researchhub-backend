from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from feed.journal_v2_serializers import (
    JOURNAL_BADGE_FUNDED_PROPOSAL,
    JOURNAL_BADGE_HAS_RESULTS,
    JOURNAL_BADGE_REGISTERED_REPORT,
)
from purchase.models import Fundraise
from reputation.models import Escrow
from researchhub_comment.constants.rh_comment_thread_references import (
    REGISTERED_REPORT_RESULTS_REFERENCE,
)
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.services.journey_service import JourneyService
from user.tests.helpers import create_random_default_user


class JournalV2FeedViewSetTests(APITestCase):
    def setUp(self) -> None:
        """Create the user, client, and service used by journal feed tests."""
        self.user = create_random_default_user("journal_v2_user")
        self.service = JourneyService()
        self.url = reverse("journal_v2_feed-list")
        self.client.force_authenticate(self.user)

    def test_list_includes_journal_proposals(self) -> None:
        """Verify the feed includes proposals from journeys in the journal."""
        # Arrange
        proposal = self.create_completed_proposal("Included proposal")
        excluded_proposal = self.create_completed_proposal(
            "Excluded proposal",
            include_in_journal=False,
        )

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post_ids = self.get_response_post_ids(response.data)
        self.assertIn(proposal.id, post_ids)
        self.assertNotIn(excluded_proposal.id, post_ids)

    def test_list_prefers_registered_reports(self) -> None:
        """Verify the feed shows the registered report when a journey has one."""
        # Arrange
        proposal = self.create_completed_proposal("Reported proposal")
        report = self.create_registered_report(proposal, "Registered report")

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post_ids = self.get_response_post_ids(response.data)
        self.assertIn(report.id, post_ids)
        self.assertNotIn(proposal.id, post_ids)

    def test_list_returns_one_card_per_journey(self) -> None:
        """Verify each journal journey contributes only its latest stage card."""
        # Arrange
        proposal = self.create_completed_proposal("Proposal only")
        reported_proposal = self.create_completed_proposal("Proposal with report")
        report = self.create_registered_report(reported_proposal, "Latest report")

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post_ids = self.get_response_post_ids(response.data)
        self.assertEqual(post_ids.count(proposal.id), 1)
        self.assertEqual(post_ids.count(report.id), 1)
        self.assertNotIn(reported_proposal.id, post_ids)
        self.assertEqual(len(post_ids), 2)

    def test_order_by_amount_raised_uses_proposal_fundraises(self) -> None:
        """Verify report cards sort by the proposal's amount raised."""
        # Arrange
        low_proposal = self.create_completed_proposal(
            "Low amount proposal",
            amount_raised=Decimal("25.00"),
        )
        low_report = self.create_registered_report(
            low_proposal,
            "Low amount report",
        )
        high_proposal = self.create_completed_proposal(
            "High amount proposal",
            amount_raised=Decimal("250.00"),
        )
        high_report = self.create_registered_report(
            high_proposal,
            "High amount report",
        )

        # Act
        response = self.client.get(self.url, {"ordering": "amount_raised"})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post_ids = self.get_response_post_ids(response.data)
        self.assertLess(post_ids.index(high_report.id), post_ids.index(low_report.id))

    def test_order_by_upvotes_uses_latest_stage_scores(self) -> None:
        """Verify journal cards sort by the visible stage's upvote score."""
        # Arrange
        low_proposal = self.create_completed_proposal("Low score proposal")
        low_report = self.create_registered_report(
            low_proposal,
            "Low score report",
            score=2,
        )
        high_proposal = self.create_completed_proposal("High score proposal")
        high_report = self.create_registered_report(
            high_proposal,
            "High score report",
            score=20,
        )

        # Act
        response = self.client.get(self.url, {"ordering": "upvotes"})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post_ids = self.get_response_post_ids(response.data)
        self.assertLess(post_ids.index(high_report.id), post_ids.index(low_report.id))

    def test_show_funded_proposal_badge(self) -> None:
        """Verify proposal cards expose the funded proposal journal badge."""
        # Arrange
        proposal = self.create_completed_proposal("Funded proposal badge")

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        content = self.get_response_content(response.data, proposal.id)
        self.assertEqual(content["journal_badge"], JOURNAL_BADGE_FUNDED_PROPOSAL)

    def test_show_registered_report_badge(self) -> None:
        """Verify report cards expose the registered report journal badge."""
        # Arrange
        proposal = self.create_completed_proposal("Registered report badge")
        report = self.create_registered_report(proposal, "Report badge")

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        content = self.get_response_content(response.data, report.id)
        self.assertEqual(content["journal_badge"], JOURNAL_BADGE_REGISTERED_REPORT)

    def test_show_results_badge(self) -> None:
        """Verify report cards expose the has-results journal badge."""
        # Arrange
        proposal = self.create_completed_proposal("Results badge proposal")
        report = self.create_registered_report(proposal, "Results badge report")
        self.create_results_update(report)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        content = self.get_response_content(response.data, report.id)
        self.assertEqual(content["journal_badge"], JOURNAL_BADGE_HAS_RESULTS)

    def create_completed_proposal(
        self,
        title: str,
        include_in_journal: bool = True,
        amount_raised: Decimal = Decimal("0.00"),
        score: int = 0,
    ) -> ResearchhubPost:
        """Create an approved proposal with a completed fundraise and journey."""
        proposal = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title=title,
        )
        proposal.score = score
        proposal.save(update_fields=["score"])
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.COMPLETED,
        )
        fundraise.escrow = self.create_fundraise_escrow(fundraise, amount_raised)
        fundraise.save(update_fields=["escrow"])

        if include_in_journal:
            self.service.include_completed_fundraise_in_journal(fundraise)
        else:
            self.service.ensure_approved_preregistration_has_journey(proposal)

        proposal.refresh_from_db()
        return proposal

    def create_registered_report(
        self, proposal: ResearchhubPost, title: str, score: int = 0
    ) -> ResearchhubPost:
        """Create and attach a registered report to a proposal journey."""
        report = create_post(
            created_by=self.user,
            document_type=REGISTERED_REPORT,
            title=title,
        )
        report.score = score
        report.save(update_fields=["score"])
        self.service.attach_stage(proposal.journey, report)
        return report

    def create_fundraise_escrow(
        self, fundraise: Fundraise, amount_raised: Decimal
    ) -> Escrow:
        """Create the escrow used by fundraise amount-raised sorting."""
        return Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.FUNDRAISE,
            amount_holding=amount_raised,
            amount_paid=Decimal("0.00"),
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=fundraise.id,
        )

    def create_results_update(self, report: ResearchhubPost) -> RhCommentModel:
        """Create a registered report results update comment."""
        thread = RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=report.id,
            created_by=self.user,
            thread_reference=REGISTERED_REPORT_RESULTS_REFERENCE,
            thread_type=AUTHOR_UPDATE,
        )
        return RhCommentModel.objects.create(
            thread=thread,
            created_by=self.user,
            comment_type=AUTHOR_UPDATE,
            comment_content_json={"ops": [{"insert": "Results"}]},
        )

    @staticmethod
    def get_response_post_ids(data: dict) -> list[int]:
        """Return post ids from a paginated journal feed response."""
        return [item["content_object"]["id"] for item in data["results"]]

    @staticmethod
    def get_response_content(data: dict, post_id: int) -> dict:
        """Return one post card payload from a paginated journal feed response."""
        for item in data["results"]:
            content = item["content_object"]
            if content["id"] == post_id:
                return content
        raise AssertionError(f"Post {post_id} was not returned.")
