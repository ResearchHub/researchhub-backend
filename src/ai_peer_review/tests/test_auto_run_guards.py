from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase, override_settings

from ai_peer_review.models import ProposalReview, ReviewStatus
from ai_peer_review.services.auto_run_guards import (
    should_skip_key_insights,
    should_skip_proposal_review,
)
from purchase.models import Grant
from researchhub_comment.constants.rh_comment_thread_types import COMMUNITY_REVIEW
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from review.models import Review
from user.tests.helpers import create_random_authenticated_user


class AutoRunProposalReviewGuardsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_random_authenticated_user("guard_pr_user")
        self.post = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Guard PR test",
        )
        self.ud = self.post.unified_document
        self.grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.ud,
            amount=Decimal("10000"),
            description="Desc",
            status=Grant.OPEN,
        )

    def tearDown(self):
        cache.clear()

    def test_skip_when_no_grant(self):
        pr = ProposalReview.objects.create(
            unified_document=self.ud,
            grant=None,
            created_by=self.user,
            status=ReviewStatus.PENDING,
        )
        skip, reason = should_skip_proposal_review(pr, force=False)
        self.assertTrue(skip)
        self.assertEqual(reason, "no_grant")

    def test_skip_when_processing(self):
        pr = ProposalReview.objects.create(
            unified_document=self.ud,
            grant=self.grant,
            created_by=self.user,
            status=ReviewStatus.PROCESSING,
        )
        skip, reason = should_skip_proposal_review(pr, force=False)
        self.assertTrue(skip)
        self.assertEqual(reason, "processing")

    def test_repeated_check_same_review_not_throttled_separately_from_daily_cap(self):
        """No min-interval cooldown; two guard checks in a row both pass if under cap."""
        pr = ProposalReview.objects.create(
            unified_document=self.ud,
            grant=self.grant,
            created_by=self.user,
            status=ReviewStatus.PENDING,
        )
        skip1, _ = should_skip_proposal_review(pr, force=False)
        self.assertFalse(skip1)
        skip2, _ = should_skip_proposal_review(pr, force=False)
        self.assertFalse(skip2)

    def test_force_bypasses_rate_limits(self):
        pr = ProposalReview.objects.create(
            unified_document=self.ud,
            grant=self.grant,
            created_by=self.user,
            status=ReviewStatus.PENDING,
        )
        should_skip_proposal_review(pr, force=False)
        skip, _ = should_skip_proposal_review(pr, force=True)
        self.assertFalse(skip)

    @override_settings(AUTO_PR_DAILY_CAP_PER_GRANT=1)
    def test_daily_cap_per_grant(self):
        other_post = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Other proposal same grant cap",
        )
        pr1 = ProposalReview.objects.create(
            unified_document=self.ud,
            grant=self.grant,
            created_by=self.user,
            status=ReviewStatus.PENDING,
        )
        pr2 = ProposalReview.objects.create(
            unified_document=other_post.unified_document,
            grant=self.grant,
            created_by=self.user,
            status=ReviewStatus.PENDING,
        )
        skip1, _ = should_skip_proposal_review(pr1, force=False)
        self.assertFalse(skip1)
        skip2, reason2 = should_skip_proposal_review(pr2, force=False)
        self.assertTrue(skip2)
        self.assertEqual(reason2, "daily_cap")


class AutoRunKeyInsightsGuardsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_random_authenticated_user("guard_ki_user")
        self.post = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Guard KI test",
        )
        self.ud = self.post.unified_document
        self.grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.ud,
            amount=Decimal("10000"),
            description="Desc",
            status=Grant.OPEN,
        )

    def tearDown(self):
        cache.clear()

    def test_skip_when_proposal_review_not_completed(self):
        pr = ProposalReview.objects.create(
            unified_document=self.ud,
            grant=self.grant,
            created_by=self.user,
            status=ReviewStatus.PENDING,
        )
        skip, reason = should_skip_key_insights(pr, force=False)
        self.assertTrue(skip)
        self.assertEqual(reason, "proposal_review_not_completed")

    def test_skip_completed_without_assessed_comments(self):
        pr = ProposalReview.objects.create(
            unified_document=self.ud,
            grant=self.grant,
            created_by=self.user,
            status=ReviewStatus.COMPLETED,
            overall_rating="good",
            overall_score_numeric=3,
        )
        skip, reason = should_skip_key_insights(pr, force=False)
        self.assertTrue(skip)
        self.assertEqual(reason, "no_assessed_comments")

    def test_passes_when_assessed_comment_exists(self):
        thread = RhCommentThreadModel.objects.create(
            content_object=self.post,
            created_by=self.user,
            updated_by=self.user,
        )
        comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "hello"}]},
            thread=thread,
            created_by=self.user,
            updated_by=self.user,
            comment_type=COMMUNITY_REVIEW,
        )
        ct = ContentType.objects.get_for_model(RhCommentModel)
        Review.objects.create(
            content_type=ct,
            object_id=comment.id,
            unified_document=self.ud,
            created_by=self.user,
            score=3.0,
            is_assessed=True,
        )
        pr = ProposalReview.objects.create(
            unified_document=self.ud,
            grant=self.grant,
            created_by=self.user,
            status=ReviewStatus.COMPLETED,
            overall_rating="good",
            overall_score_numeric=3,
        )
        skip, _ = should_skip_key_insights(pr, force=False)
        self.assertFalse(skip)
