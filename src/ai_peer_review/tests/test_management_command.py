"""Tests for ``manage.py run_proposal_reviews``."""

from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from ai_peer_review.models import ProposalReview, Status
from purchase.models import Grant, GrantApplication
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.tests.helpers import create_random_authenticated_user


class RunProposalReviewsCommandTests(TestCase):
    def setUp(self):
        self.actor = create_random_authenticated_user("cmd_actor", moderator=True)
        self.applicant = create_random_authenticated_user("cmd_applicant")
        self.grant_post = create_post(created_by=self.actor, document_type=GRANT)
        self.grant = Grant.objects.create(
            created_by=self.actor,
            unified_document=self.grant_post.unified_document,
            amount=Decimal("5000.00"),
            currency="USD",
            organization="Cmd Org",
            description="Grant for command tests",
            status=Grant.OPEN,
            end_date=timezone.now() + timedelta(days=30),
        )
        self.prop_post = create_post(
            created_by=self.applicant,
            document_type=PREREGISTRATION,
            title="Cmd Proposal",
        )
        self.ud = self.prop_post.unified_document
        GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.prop_post,
            applicant=self.applicant,
        )

    def test_rejects_neither_mode_nor_both_modes(self):
        with self.assertRaises(CommandError):
            call_command("run_proposal_reviews", stdout=StringIO())
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "run_proposal_reviews",
                grant_ids="1",
                created_after="2020-01-01",
                stdout=out,
            )

    @patch(
        "ai_peer_review.management.commands.run_proposal_reviews."
        "run_executive_comparison"
    )
    @patch(
        "ai_peer_review.management.commands.run_proposal_reviews.run_proposal_review"
    )
    def test_grant_ids_processes_regardless_of_status(
        self, mock_run_review, mock_run_exec
    ):
        self.grant.status = Grant.CLOSED
        self.grant.end_date = timezone.now() - timedelta(days=1)
        self.grant.save()
        out = StringIO()
        call_command(
            "run_proposal_reviews",
            grant_ids=str(self.grant.id),
            stdout=out,
        )
        mock_run_review.assert_called_once()
        mock_run_exec.assert_called_once_with(self.grant.id, None)

    @patch(
        "ai_peer_review.management.commands.run_proposal_reviews."
        "run_executive_comparison"
    )
    @patch(
        "ai_peer_review.management.commands.run_proposal_reviews.run_proposal_review"
    )
    def test_created_after_filters_non_open_grants(
        self, mock_run_review, mock_run_exec
    ):
        closed_post = create_post(created_by=self.actor, document_type=GRANT)
        closed_grant = Grant.objects.create(
            created_by=self.actor,
            unified_document=closed_post.unified_document,
            amount=Decimal("1000.00"),
            currency="USD",
            organization="Closed",
            description="Closed grant",
            status=Grant.CLOSED,
        )
        # Recent created_date so it would match date filter alone
        closed_grant.created_date = timezone.now() - timedelta(days=1)
        closed_grant.save(update_fields=["created_date"])

        yesterday = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        out = StringIO()
        call_command(
            "run_proposal_reviews",
            created_after=yesterday,
            stdout=out,
        )
        # Only OPEN + future deadline grant (self.grant), not closed_grant
        self.assertEqual(mock_run_review.call_count, 1)
        mock_run_review.assert_called_with(
            ProposalReview.objects.get(grant=self.grant, unified_document=self.ud).id
        )

    @patch(
        "ai_peer_review.management.commands.run_proposal_reviews."
        "run_executive_comparison"
    )
    @patch(
        "ai_peer_review.management.commands.run_proposal_reviews.run_proposal_review"
    )
    def test_skips_completed_reruns_failed(self, mock_run_review, mock_run_exec):
        ProposalReview.objects.create(
            created_by=self.actor,
            unified_document=self.ud,
            grant=self.grant,
            status=Status.COMPLETED,
            overall_rating="good",
            overall_score_numeric=4,
        )
        out = StringIO()
        call_command(
            "run_proposal_reviews",
            grant_ids=str(self.grant.id),
            stdout=out,
        )
        mock_run_review.assert_not_called()
        mock_run_exec.assert_called_once()

        mock_run_review.reset_mock()
        mock_run_exec.reset_mock()
        ProposalReview.objects.filter(
            grant=self.grant, unified_document=self.ud
        ).update(status=Status.FAILED, error_message="x")
        call_command(
            "run_proposal_reviews",
            grant_ids=str(self.grant.id),
            stdout=out,
        )
        mock_run_review.assert_called_once()
        mock_run_exec.assert_called_once()

    @patch(
        "ai_peer_review.management.commands.run_proposal_reviews."
        "run_executive_comparison"
    )
    @patch(
        "ai_peer_review.management.commands.run_proposal_reviews.run_proposal_review"
    )
    def test_force_reruns_completed(self, mock_run_review, mock_run_exec):
        ProposalReview.objects.create(
            created_by=self.actor,
            unified_document=self.ud,
            grant=self.grant,
            status=Status.COMPLETED,
            overall_rating="good",
            overall_score_numeric=4,
        )
        out = StringIO()
        call_command(
            "run_proposal_reviews",
            grant_ids=str(self.grant.id),
            force=True,
            stdout=out,
        )
        mock_run_review.assert_called_once()
        mock_run_exec.assert_called_once_with(self.grant.id, None)
