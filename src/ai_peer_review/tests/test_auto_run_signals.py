from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from ai_peer_review.models import ProposalReview, Status
from purchase.models import Grant, GrantApplication
from researchhub_comment.constants.rh_comment_thread_types import COMMUNITY_REVIEW
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from review.models import Review
from user.related_models.user_model import FOUNDATION_EMAIL
from user.tests.helpers import create_random_authenticated_user, create_user


class AutoRunProposalReviewPostSaveSignalTests(TestCase):
    @patch("ai_peer_review.tasks.auto_run_proposal_reviews_for_post.delay")
    def test_preregistration_post_save_enqueues_auto_run(self, mock_delay):
        user = create_random_authenticated_user("sig_post_user")
        with self.captureOnCommitCallbacks(execute=True):
            post = create_post(
                created_by=user,
                document_type=PREREGISTRATION,
                title="Signal post",
            )
        post.title = "Updated title"
        with self.captureOnCommitCallbacks(execute=True):
            post.save(update_fields=["title"])
        mock_delay.assert_any_call(post.id, force=False)


class AutoRunGrantApplicationSignalTests(TestCase):
    @patch("ai_peer_review.tasks.auto_run_proposal_review_for_grant_application.delay")
    def test_grant_application_create_enqueues_auto_run(self, mock_delay):
        owner = create_random_authenticated_user("sig_app_owner")
        applicant = create_random_authenticated_user("sig_app_applicant")
        prop_post = create_post(
            created_by=applicant,
            document_type=PREREGISTRATION,
            title="Applicant proposal",
        )
        grant_post = create_post(
            created_by=owner,
            document_type=PREREGISTRATION,
            title="Proposal",
        )
        grant = Grant.objects.create(
            created_by=owner,
            unified_document=grant_post.unified_document,
            amount=Decimal("5000"),
            description="Grant description here.",
            status=Grant.OPEN,
        )
        mock_delay.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            grant_application = GrantApplication.objects.create(
                grant=grant,
                preregistration_post=prop_post,
                applicant=applicant,
            )
        mock_delay.assert_called_once_with(grant_application.id, force=False)


class AutoRunKeyInsightsReviewSignalTests(TestCase):
    @patch("ai_peer_review.tasks.auto_run_proposal_key_insights_for_ud.delay")
    def test_review_assessed_triggers_key_insights_fanout(self, mock_delay):
        user = create_random_authenticated_user("sig_ki_user")
        post = create_post(
            created_by=user,
            document_type=PREREGISTRATION,
            title="KI signal",
        )
        ud = post.unified_document
        ct = ContentType.objects.get_for_model(RhCommentModel)
        thread = RhCommentThreadModel.objects.create(
            content_object=post,
            created_by=user,
            updated_by=user,
        )
        comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "x"}]},
            thread=thread,
            created_by=user,
            updated_by=user,
            comment_type=COMMUNITY_REVIEW,
        )
        with self.captureOnCommitCallbacks(execute=True):
            Review.objects.create(
                content_type=ct,
                object_id=comment.id,
                unified_document=ud,
                created_by=user,
                score=4.0,
                is_assessed=True,
            )
        mock_delay.assert_called_with(ud.id, force=False)


class AutoRunKeyInsightsCommentUpdateTests(TestCase):
    @patch("ai_peer_review.tasks.auto_run_proposal_key_insights_for_ud.delay")
    def test_comment_update_enqueues_when_review_assessed(self, mock_delay):
        user = create_random_authenticated_user("sig_ki_edit_user")
        post = create_post(
            created_by=user,
            document_type=PREREGISTRATION,
            title="KI comment edit",
        )
        ud = post.unified_document
        thread = RhCommentThreadModel.objects.create(
            content_object=post,
            created_by=user,
            updated_by=user,
        )
        comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "original"}]},
            thread=thread,
            created_by=user,
            updated_by=user,
            comment_type=COMMUNITY_REVIEW,
        )
        ct = ContentType.objects.get_for_model(RhCommentModel)
        with self.captureOnCommitCallbacks(execute=True):
            Review.objects.create(
                content_type=ct,
                object_id=comment.id,
                unified_document=ud,
                created_by=user,
                score=4.0,
                is_assessed=True,
            )
        mock_delay.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            comment.comment_content_json = {"ops": [{"insert": "edited body"}]}
            comment.save(update_fields=["comment_content_json", "updated_date"])
        mock_delay.assert_called_once_with(ud.id, force=False)


class AutoRunKeyInsightsPurchaseBridgeTests(TestCase):
    """RHF tip uses Review.objects.update(); bridge dispatches key-insights fan-out."""

    @patch("ai_peer_review.tasks.auto_run_proposal_key_insights_for_ud.delay")
    def test_foundation_purchase_dispatches_after_assessed_update(self, mock_delay):
        foundation = create_user(email=FOUNDATION_EMAIL)
        reviewer = create_random_authenticated_user("bridge_reviewer")
        post = create_post(
            created_by=reviewer,
            document_type=PREREGISTRATION,
            title="Bridge proposal",
        )
        thread = RhCommentThreadModel.objects.create(
            content_object=post,
            created_by=reviewer,
            updated_by=reviewer,
        )
        comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "review body"}]},
            thread=thread,
            created_by=reviewer,
            updated_by=reviewer,
            comment_type=COMMUNITY_REVIEW,
        )
        ct = ContentType.objects.get_for_model(comment)
        Review.objects.create(
            content_type=ct,
            object_id=comment.id,
            unified_document=post.unified_document,
            created_by=reviewer,
            score=5.0,
            is_assessed=False,
        )
        from purchase.related_models.purchase_model import Purchase

        with self.captureOnCommitCallbacks(execute=True):
            Purchase.objects.create(
                user=foundation,
                content_type=ct,
                object_id=comment.id,
                purchase_type=Purchase.BOOST,
                purchase_method=Purchase.OFF_CHAIN,
                paid_status=Purchase.PAID,
                amount=10,
            )
        mock_delay.assert_called_with(post.unified_document_id, force=False)


class AutoRunProposalReviewCompletedSignalTests(TestCase):
    @patch("ai_peer_review.tasks.auto_run_proposal_key_insights_for_ud.delay")
    def test_proposal_review_completed_triggers_fanout(self, mock_delay):
        user = create_random_authenticated_user("sig_pr_done")
        post = create_post(
            created_by=user,
            document_type=PREREGISTRATION,
            title="PR completed",
        )
        grant_post = create_post(
            created_by=user,
            document_type=PREREGISTRATION,
            title="Grant ud",
        )
        grant = Grant.objects.create(
            created_by=user,
            unified_document=grant_post.unified_document,
            amount=Decimal("1000"),
            description="Desc",
            status=Grant.OPEN,
        )
        pr = ProposalReview.objects.create(
            unified_document=post.unified_document,
            grant=grant,
            created_by=user,
            status=Status.PENDING,
        )
        pr.status = Status.COMPLETED
        pr.overall_rating = "good"
        pr.overall_score_numeric = 3
        with self.captureOnCommitCallbacks(execute=True):
            pr.save(
                update_fields=[
                    "status",
                    "overall_rating",
                    "overall_score_numeric",
                    "updated_date",
                ]
            )
        mock_delay.assert_called_with(post.unified_document_id, force=False)
