from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from discussion.tests.helpers import create_paper
from purchase.related_models.purchase_model import Purchase
from reputation.models import Bounty, BountySolution
from reputation.related_models.escrow import Escrow
from researchhub_comment.tests.helpers import create_rh_comment
from review.models import Review
from user.related_models.user_model import FOUNDATION_EMAIL
from user.tests.helpers import create_random_default_user, create_user


class ReviewAssessedOnPurchaseSignalTests(TestCase):
    def setUp(self):
        self.foundation = create_user(email=FOUNDATION_EMAIL)
        self.reviewer = create_random_default_user("reviewer")
        self.paper = create_paper(uploaded_by=self.reviewer)
        self.comment = create_rh_comment(paper=self.paper, created_by=self.reviewer)
        self.comment_ct = ContentType.objects.get_for_model(self.comment)
        self.review = Review.objects.create(
            created_by=self.reviewer,
            content_type=self.comment_ct,
            object_id=self.comment.id,
            unified_document=self.paper.unified_document,
            score=7,
        )

    def _create_purchase(self, user):
        return Purchase.objects.create(
            user=user,
            content_type=self.comment_ct,
            object_id=self.comment.id,
            purchase_type=Purchase.BOOST,
            purchase_method=Purchase.OFF_CHAIN,
            paid_status=Purchase.PAID,
            amount=10,
        )

    def test_foundation_purchase_marks_review_assessed(self):
        self._create_purchase(self.foundation)
        self.review.refresh_from_db()
        self.assertTrue(self.review.is_assessed)

    @patch("ai_peer_review.tasks.auto_run_proposal_key_insights_for_ud.delay")
    def test_foundation_purchase_enqueues_key_insights_with_force_true(self, mock_ki):
        with self.captureOnCommitCallbacks(execute=True):
            self._create_purchase(self.foundation)
        mock_ki.assert_called_once_with(
            self.paper.unified_document_id,
            force=True,
        )

    def test_non_foundation_purchase_does_not_mark_assessed(self):
        other = create_random_default_user("tipper")
        self._create_purchase(other)
        self.review.refresh_from_db()
        self.assertFalse(self.review.is_assessed)

    def test_foundation_purchase_on_non_comment_does_not_mark_assessed(self):
        paper_ct = ContentType.objects.get_for_model(self.paper)
        Purchase.objects.create(
            user=self.foundation,
            content_type=paper_ct,
            object_id=self.paper.id,
            purchase_type=Purchase.BOOST,
            purchase_method=Purchase.OFF_CHAIN,
            paid_status=Purchase.PAID,
            amount=10,
        )
        self.review.refresh_from_db()
        self.assertFalse(self.review.is_assessed)

    def test_already_assessed_review_stays_assessed_on_second_purchase(self):
        self.review.is_assessed = True
        self.review.save()
        self._create_purchase(self.foundation)
        self.review.refresh_from_db()
        self.assertTrue(self.review.is_assessed)


class ReviewAssessedOnBountyAwardSignalTests(TestCase):
    def setUp(self):
        self.foundation = create_user(email=FOUNDATION_EMAIL)
        self.reviewer = create_random_default_user("reviewer_bounty")
        self.paper = create_paper(uploaded_by=self.reviewer)
        self.comment = create_rh_comment(paper=self.paper, created_by=self.reviewer)
        self.comment_ct = ContentType.objects.get_for_model(self.comment)
        self.review = Review.objects.create(
            created_by=self.reviewer,
            content_type=self.comment_ct,
            object_id=self.comment.id,
            unified_document=self.paper.unified_document,
            score=8,
        )
        self.escrow = Escrow.objects.create(
            hold_type=Escrow.BOUNTY,
            created_by=self.foundation,
            content_type=self.comment_ct,
            object_id=self.comment.id,
            amount_holding=100,
        )
        self.bounty = Bounty.objects.create(
            created_by=self.foundation,
            escrow=self.escrow,
            item=self.comment,
            unified_document=self.paper.unified_document,
            amount=100,
        )

    def _create_solution(self, bounty_creator=None):
        if bounty_creator is not None:
            self.bounty.created_by = bounty_creator
            self.bounty.save()
        solution = BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.reviewer,
            content_type=self.comment_ct,
            object_id=self.comment.id,
        )
        return solution

    def test_awarding_foundation_bounty_marks_review_assessed(self):
        solution = self._create_solution()
        solution.award(amount=100)
        self.review.refresh_from_db()
        self.assertTrue(self.review.is_assessed)

    @patch("ai_peer_review.tasks.auto_run_proposal_key_insights_for_ud.delay")
    def test_bounty_award_enqueues_key_insights_with_force_true(self, mock_ki):
        solution = self._create_solution()
        with self.captureOnCommitCallbacks(execute=True):
            solution.award(amount=100)
        mock_ki.assert_called_once_with(
            self.paper.unified_document_id,
            force=True,
        )

    def test_submitted_solution_does_not_mark_assessed(self):
        self._create_solution()
        self.review.refresh_from_db()
        self.assertFalse(self.review.is_assessed)

    def test_non_foundation_bounty_award_does_not_mark_assessed(self):
        other = create_random_default_user("other_bounty_creator")
        solution = self._create_solution(bounty_creator=other)
        solution.award(amount=100)
        self.review.refresh_from_db()
        self.assertFalse(self.review.is_assessed)
