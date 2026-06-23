from decimal import Decimal

from rest_framework.test import APITestCase

from purchase.models import Fundraise
from researchhub_comment.constants.rh_comment_content_types import QUILL_EDITOR
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
)
from researchhub_document.services.journey_service import (
    REGISTERED_REPORT_RESULTS_REFERENCE,
    JourneyService,
)
from user.models import User
from user.tests.helpers import create_random_default_user


class AppendRegisteredReportResultsTests(APITestCase):
    results_url = "/api/researchhubpost/append-registered-report-results/"

    def setUp(self) -> None:
        """Create users and service dependencies for results update tests."""
        self.user = create_random_default_user("rr_results_owner")
        self.moderator = create_random_default_user(
            "rr_results_moderator",
            moderator=True,
        )
        self.service = JourneyService()
        self.client.force_authenticate(self.user)

    def test_append_results_creates_author_update(self) -> None:
        """Verify report results create an author-update comment on the report."""
        # Arrange
        report = self._create_registered_report(self.user)
        original_title = report.title
        original_body = report.renderable_text
        payload = self._build_payload(report)

        # Act
        response = self.client.post(self.results_url, payload, format="json")

        # Assert
        self.assertEqual(response.status_code, 200)
        comment = RhCommentModel.objects.get(id=response.data["id"])
        thread = comment.thread
        report.refresh_from_db()
        self.assertEqual(report.title, original_title)
        self.assertEqual(report.renderable_text, original_body)
        self.assertEqual(comment.created_by, self.user)
        self.assertEqual(comment.comment_type, AUTHOR_UPDATE)
        self.assertEqual(comment.comment_content_type, QUILL_EDITOR)
        self.assertEqual(comment.comment_content_json, payload["comment_content_json"])
        self.assertEqual(comment.context_title, payload["context_title"])
        self.assertEqual(thread.content_object, report)
        self.assertEqual(thread.thread_type, AUTHOR_UPDATE)
        self.assertEqual(
            thread.thread_reference,
            REGISTERED_REPORT_RESULTS_REFERENCE,
        )

    def test_reject_moderator_for_other_owner(self) -> None:
        """Verify moderators cannot append results to another user's report."""
        # Arrange
        report = self._create_registered_report(self.user)
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            self.results_url,
            self._build_payload(report),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertFalse(RhCommentModel.objects.exists())
        self.assertFalse(RhCommentThreadModel.objects.exists())

    def test_reject_non_report_target(self) -> None:
        """Verify results cannot be appended to a proposal post."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        payload = self._build_payload(proposal)

        # Act
        response = self.client.post(self.results_url, payload, format="json")

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertFalse(RhCommentModel.objects.exists())
        self.assertFalse(RhCommentThreadModel.objects.exists())

    def test_require_login(self) -> None:
        """Verify anonymous users cannot append registered report results."""
        # Arrange
        report = self._create_registered_report(self.user)
        self.client.force_authenticate(None)

        # Act
        response = self.client.post(
            self.results_url,
            self._build_payload(report),
            format="json",
        )

        # Assert
        self.assertIn(response.status_code, (401, 403))

    def _build_payload(self, post: ResearchhubPost) -> dict[str, object]:
        """Build a valid registered report results request payload."""
        return {
            "registered_report_id": post.id,
            "comment_content_json": {
                "ops": [{"insert": "Registered report results."}],
            },
            "context_title": "Results",
        }

    def _create_registered_report(self, user: User) -> ResearchhubPost:
        """Create a registered report attached to a completed proposal."""
        proposal = self._create_completed_proposal(user)
        return self.service.create_registered_report(
            user=user,
            proposal_id=proposal.id,
            title="Registered report title",
            renderable_text=(
                "Registered report body. Registered report body. "
                "Registered report body."
            ),
        )

    def _create_completed_proposal(self, user: User) -> ResearchhubPost:
        """Create an approved proposal with a completed fundraise."""
        proposal = create_post(
            created_by=user,
            document_type=PREREGISTRATION,
            title=f"{user.id} proposal title",
        )
        proposal.authors.add(user.author_profile)
        fundraise = Fundraise.objects.create(
            created_by=user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.COMPLETED,
        )
        self.service.include_completed_fundraise_in_journal(fundraise)
        proposal.refresh_from_db()
        return proposal
