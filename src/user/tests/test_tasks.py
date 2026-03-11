from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from discussion.constants.flag_reasons import ABUSIVE_OR_RUDE, SPAM
from discussion.models import Flag
from discussion.views import censor
from note.models import Note
from paper.tests.helpers import create_paper
from purchase.models import Fundraise, Grant, Purchase
from reputation.models import Bounty, Escrow
from researchhub_comment.models import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from review.models.peer_review_model import PeerReview
from review.models.review_model import Review
from user.models import Action
from user.related_models.verdict_model import Verdict
from user.tasks import get_latest_actions, handle_spam_user_task, reinstate_user_task
from user.tests.helpers import create_actions, create_random_default_user


class UserTasksTests(TestCase):
    def setUp(self):
        pass

    def test_get_lastest_actions(self):
        first_action = create_actions(1)
        create_actions(9)
        last_cursor = 1

        latest_actions, next_cursor = get_latest_actions(last_cursor)

        self.assertEqual(len(latest_actions), 9)
        self.assertFalse(first_action in latest_actions)

        latest_actions, next_cursor = get_latest_actions(next_cursor)

        self.assertEqual(len(latest_actions), 0)

        latest_actions, next_cursor = get_latest_actions(3)

        self.assertEqual(len(latest_actions), 7)
        self.assertFalse(first_action in latest_actions)


class HandleSpamUserTaskTests(TestCase):
    def setUp(self):
        # Create a user
        self.user = create_random_default_user("spam_user")
        self.moderator = create_random_default_user("moderator", moderator=True)

        # Create a paper uploaded by the user
        self.paper = create_paper(title="Test Paper Title", uploaded_by=self.user)

        # Create a post by the user
        self.post = ResearchhubPost.objects.create(
            created_by=self.user,
            title="Test Post",
            renderable_text="Test content",
            document_type="DISCUSSION",
            unified_document=ResearchhubUnifiedDocument.objects.create(
                document_type="DISCUSSION"
            ),
        )

        # Create a thread for the comment
        self.thread = RhCommentThreadModel.objects.create(
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(self.post),
            object_id=self.post.id,
        )

        # Create a comment by the user with proper content_json format
        self.comment = RhCommentModel.objects.create(
            created_by=self.user,
            comment_content_json={"ops": [{"insert": "Test comment"}]},
            thread=self.thread,
        )

        # Create an action for the user
        self.action = Action.objects.create(
            user=self.user,
            display=True,
            is_removed=False,
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
        )

    def test_handle_spam_user_task_without_requestor(self):
        """Test that the task properly marks content as removed without a requestor"""
        # Execute the task
        handle_spam_user_task(self.user.id)

        # Refresh objects from database
        self.paper.refresh_from_db()
        self.post.unified_document.refresh_from_db()
        self.action.refresh_from_db()
        self.comment.refresh_from_db()

        # Check if paper is marked as removed
        self.assertTrue(self.paper.is_removed)

        # Check if paper's unified document is marked as removed
        unified_doc = ResearchhubUnifiedDocument.all_objects.get(paper=self.paper)
        self.assertTrue(unified_doc.is_removed)

        # Check if post's unified document is marked as removed
        self.assertTrue(self.post.unified_document.is_removed)

        # Check if user's actions are marked as removed and not displayed
        self.assertTrue(self.action.is_removed)
        self.assertFalse(self.action.display)

        # Comment should still be visible as there was no requestor to censor it
        self.assertFalse(self.comment.is_removed)

    def test_handle_spam_user_task_with_requestor(self):
        """Test that the task properly marks content as removed with a requestor"""
        # Execute the task with a requestor
        handle_spam_user_task(self.user.id, self.moderator)

        # Refresh objects from database
        self.paper.refresh_from_db()
        self.post.unified_document.refresh_from_db()
        self.action.refresh_from_db()
        self.comment.refresh_from_db()

        # Check if paper is marked as removed
        self.assertTrue(self.paper.is_removed)

        # Check if paper's unified document is marked as removed
        unified_doc = ResearchhubUnifiedDocument.all_objects.get(paper=self.paper)
        self.assertTrue(unified_doc.is_removed)

        # Check if post's unified document is marked as removed
        self.assertTrue(self.post.unified_document.is_removed)

        # Check if user's actions are marked as removed and not displayed
        self.assertTrue(self.action.is_removed)
        self.assertFalse(self.action.display)

        # Comment should be removed since there was a requestor to censor it
        self.assertTrue(self.comment.is_removed)

    def test_handle_spam_user_task_with_multiple_contents(self):
        """Test that the task handles multiple content items properly"""
        # Create additional papers, posts, and comments
        paper2 = create_paper(title="Second Test Paper", uploaded_by=self.user)

        post2 = ResearchhubPost.objects.create(
            created_by=self.user,
            title="Second Post",
            renderable_text="Second content",
            document_type="DISCUSSION",
            unified_document=ResearchhubUnifiedDocument.objects.create(
                document_type="DISCUSSION"
            ),
        )

        # Create a thread for the second comment
        thread2 = RhCommentThreadModel.objects.create(
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(post2),
            object_id=post2.id,
        )

        # Create a comment with proper content_json format
        comment2 = RhCommentModel.objects.create(
            created_by=self.user,
            comment_content_json={"ops": [{"insert": "Second comment"}]},
            thread=thread2,
        )

        # Execute the task
        handle_spam_user_task(self.user.id, self.moderator)

        # Refresh objects from database
        self.paper.refresh_from_db()
        self.post.unified_document.refresh_from_db()
        self.comment.refresh_from_db()
        paper2.refresh_from_db()
        post2.unified_document.refresh_from_db()
        comment2.refresh_from_db()

        # Check if all papers are marked as removed
        self.assertTrue(self.paper.is_removed)
        self.assertTrue(paper2.is_removed)

        # Check if all post unified documents are marked as removed
        self.assertTrue(self.post.unified_document.is_removed)
        self.assertTrue(post2.unified_document.is_removed)

        # Check if all comments are marked as removed
        self.assertTrue(self.comment.is_removed)
        self.assertTrue(comment2.is_removed)

    def test_reinstate_user_task(self):
        """Test that reinstate_user_task properly restores user content"""
        # First, suspend the user to set up the test
        handle_spam_user_task(self.user.id, self.moderator)

        # Verify everything is removed
        self.paper.refresh_from_db()
        self.post.unified_document.refresh_from_db()
        self.comment.refresh_from_db()
        self.action.refresh_from_db()

        self.assertTrue(self.paper.is_removed)
        self.assertTrue(self.post.unified_document.is_removed)
        self.assertTrue(self.comment.is_removed)
        self.assertTrue(self.action.is_removed)

        # Now reinstate the user
        reinstate_user_task(self.user.id)

        # Refresh objects
        self.paper.refresh_from_db()
        self.post.unified_document.refresh_from_db()
        self.comment.refresh_from_db()
        self.action.refresh_from_db()

        # Check papers and unified documents are restored
        self.assertFalse(self.paper.is_removed)
        paper_unified_doc = ResearchhubUnifiedDocument.all_objects.get(paper=self.paper)
        self.assertFalse(paper_unified_doc.is_removed)

        # Check post's unified document is restored
        self.assertFalse(self.post.unified_document.is_removed)

        # Check comment is restored
        self.assertFalse(self.comment.is_removed)
        self.assertTrue(self.comment.is_public)
        self.assertIsNone(self.comment.is_removed_date)

        # Check action is restored
        self.assertFalse(self.action.is_removed)
        self.assertTrue(self.action.display)

    def test_reinstate_user_task_with_multiple_content(self):
        """Test reinstatement with multiple content items"""
        # Create additional papers and posts
        paper2 = create_paper(title="Second Test Paper", uploaded_by=self.user)

        post2 = ResearchhubPost.objects.create(
            created_by=self.user,
            title="Second Post",
            renderable_text="Second content",
            document_type="DISCUSSION",
            unified_document=ResearchhubUnifiedDocument.objects.create(
                document_type="DISCUSSION"
            ),
        )

        # Create a thread for the second comment
        thread2 = RhCommentThreadModel.objects.create(
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(post2),
            object_id=post2.id,
        )

        # Create a second comment
        comment2 = RhCommentModel.objects.create(
            created_by=self.user,
            comment_content_json={"ops": [{"insert": "Second comment"}]},
            thread=thread2,
        )

        # First, suspend the user
        handle_spam_user_task(self.user.id, self.moderator)

        # Verify everything is removed
        self.paper.refresh_from_db()
        self.post.unified_document.refresh_from_db()
        self.comment.refresh_from_db()
        paper2.refresh_from_db()
        post2.unified_document.refresh_from_db()
        comment2.refresh_from_db()

        self.assertTrue(self.paper.is_removed)
        self.assertTrue(self.post.unified_document.is_removed)
        self.assertTrue(self.comment.is_removed)
        self.assertTrue(paper2.is_removed)
        self.assertTrue(post2.unified_document.is_removed)
        self.assertTrue(comment2.is_removed)

        # Now reinstate the user
        reinstate_user_task(self.user.id)

        # Refresh objects
        self.paper.refresh_from_db()
        self.post.unified_document.refresh_from_db()
        self.comment.refresh_from_db()
        paper2.refresh_from_db()
        post2.unified_document.refresh_from_db()
        comment2.refresh_from_db()

        # Check all papers and unified documents are restored
        self.assertFalse(self.paper.is_removed)
        self.assertFalse(self.post.unified_document.is_removed)
        self.assertFalse(paper2.is_removed)
        self.assertFalse(post2.unified_document.is_removed)

        # Check all comments are restored
        self.assertFalse(self.comment.is_removed)
        self.assertFalse(comment2.is_removed)


class HandleSpamUserContentTests(HandleSpamUserTaskTests):
    def setUp(self):
        super().setUp()
        self.other_user = create_random_default_user("content_other_user")

    def test_suspend_removes_all_new_content_types(self):
        """Notes, peer reviews, reviews, and grants are all removed on suspend."""
        # Arrange
        note_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="NOTE"
        )
        note = Note.objects.create(
            created_by=self.user,
            title="Spam Note",
            unified_document=note_unified_doc,
        )

        peer_review = PeerReview.objects.create(user=self.user, paper=self.paper)

        other_thread = RhCommentThreadModel.objects.create(
            created_by=self.other_user,
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
        )
        other_comment = RhCommentModel.objects.create(
            created_by=self.other_user,
            comment_content_json={"ops": [{"insert": "Other comment"}]},
            thread=other_thread,
        )
        review = Review.objects.create(
            created_by=self.user,
            score=5.0,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=other_comment.id,
        )

        grant_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="GRANT"
        )
        ResearchhubPost.objects.create(
            created_by=self.user,
            title="Grant Post",
            renderable_text="Grant content",
            document_type="GRANT",
            unified_document=grant_unified_doc,
        )
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_unified_doc,
            amount=Decimal("10000"),
            organization="Test Org",
            description="Test grant",
            status=Grant.OPEN,
        )

        # Act
        handle_spam_user_task(self.user.id, self.moderator)

        # Assert
        note_unified_doc.refresh_from_db()
        self.assertTrue(note_unified_doc.is_removed)

        peer_review.refresh_from_db()
        self.assertTrue(peer_review.is_removed)
        self.assertFalse(peer_review.is_public)

        review = Review.all_objects.get(id=review.id)
        self.assertTrue(review.is_removed)
        self.assertFalse(review.is_public)

        grant.refresh_from_db()
        self.assertEqual(grant.status, Grant.CLOSED)

    def test_suspend_cancels_open_bounties(self):
        """Open bounties created by the user on other users' content are cancelled."""
        # Arrange
        other_post = ResearchhubPost.objects.create(
            created_by=self.other_user,
            title="Other Post",
            renderable_text="Other content",
            document_type="DISCUSSION",
            unified_document=ResearchhubUnifiedDocument.objects.create(
                document_type="DISCUSSION"
            ),
        )
        other_thread = RhCommentThreadModel.objects.create(
            created_by=self.other_user,
            content_type=ContentType.objects.get_for_model(other_post),
            object_id=other_post.id,
        )
        other_comment = RhCommentModel.objects.create(
            created_by=self.other_user,
            comment_content_json={"ops": [{"insert": "Other comment"}]},
            thread=other_thread,
        )

        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            amount_holding=Decimal("100"),
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=other_comment.id,
        )
        bounty = Bounty.objects.create(
            created_by=self.user,
            amount=Decimal("100"),
            status=Bounty.OPEN,
            bounty_type=Bounty.Type.ANSWER,
            item_content_type=ContentType.objects.get_for_model(RhCommentModel),
            item_object_id=other_comment.id,
            escrow=escrow,
            unified_document=other_post.unified_document,
        )

        # Act
        handle_spam_user_task(self.user.id, self.moderator)

        # Assert
        bounty.refresh_from_db()
        escrow.refresh_from_db()
        self.assertEqual(bounty.status, Bounty.CANCELLED)
        self.assertEqual(escrow.amount_holding, Decimal("0"))

    def test_suspend_closes_fundraises_and_refunds_escrow(self):
        """Open fundraises are closed and escrowed RSC is refunded to contributors."""
        # Arrange
        prereg_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION"
        )
        prereg_post = ResearchhubPost.objects.create(
            created_by=self.user,
            title="Preregistration",
            renderable_text="Prereg content",
            document_type="PREREGISTRATION",
            unified_document=prereg_unified_doc,
        )

        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.FUNDRAISE,
            amount_holding=Decimal("100"),
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=prereg_unified_doc.id,
        )
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=prereg_unified_doc,
            escrow=escrow,
            status=Fundraise.OPEN,
            goal_amount=Decimal("1000"),
        )

        Purchase.objects.create(
            user=self.other_user,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=fundraise.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount="100",
        )

        # Act
        handle_spam_user_task(self.user.id, self.moderator)

        # Assert
        fundraise.refresh_from_db()
        escrow.refresh_from_db()
        self.assertEqual(fundraise.status, Fundraise.CLOSED)
        self.assertEqual(escrow.amount_holding, Decimal("0"))

    def test_suspend_resolves_open_flags(self):
        """Open flags on the user's content get verdicts matching original reason."""
        # Arrange
        flagger = self.other_user
        paper_flag = Flag.objects.create(
            created_by=flagger,
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
            reason_choice=SPAM,
        )
        comment_flag = Flag.objects.create(
            created_by=flagger,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=self.comment.id,
            reason_choice=ABUSIVE_OR_RUDE,
        )

        # Act
        handle_spam_user_task(self.user.id, self.moderator)

        # Assert
        paper_verdict = Verdict.objects.get(flag=paper_flag)
        self.assertTrue(paper_verdict.is_content_removed)
        self.assertEqual(paper_verdict.verdict_choice, SPAM)

        comment_verdict = Verdict.objects.get(flag=comment_flag)
        self.assertTrue(comment_verdict.is_content_removed)
        self.assertEqual(comment_verdict.verdict_choice, ABUSIVE_OR_RUDE)

    def test_reinstate_restores_new_content_types(self):
        """Notes, peer reviews, and reviews are restored on reinstate."""
        # Arrange
        note_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="NOTE"
        )
        note = Note.objects.create(
            created_by=self.user,
            title="Spam Note",
            unified_document=note_unified_doc,
        )

        peer_review = PeerReview.objects.create(user=self.user, paper=self.paper)

        review = Review.objects.create(
            created_by=self.user,
            score=5.0,
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
        )

        handle_spam_user_task(self.user.id, self.moderator)

        # Act
        reinstate_user_task(self.user.id)

        # Assert
        note_unified_doc.refresh_from_db()
        self.assertFalse(note_unified_doc.is_removed)

        peer_review = PeerReview.all_objects.get(id=peer_review.id)
        self.assertFalse(peer_review.is_removed)
        self.assertTrue(peer_review.is_public)

        review = Review.all_objects.get(id=review.id)
        self.assertFalse(review.is_removed)
        self.assertTrue(review.is_public)


class CensorFunctionTests(TestCase):
    def test_censor_soft_deletes_reviews(self):
        """censor() soft-deletes reviews instead of hard-deleting them."""
        # Arrange
        user = create_random_default_user("censor_user")
        paper = create_paper(title="Censor Paper", uploaded_by=user)

        thread = RhCommentThreadModel.objects.create(
            created_by=user,
            content_type=ContentType.objects.get_for_model(paper),
            object_id=paper.id,
        )
        comment = RhCommentModel.objects.create(
            created_by=user,
            comment_content_json={"ops": [{"insert": "Test comment"}]},
            thread=thread,
        )
        review = Review.objects.create(
            created_by=user,
            score=7.0,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=comment.id,
        )

        # Act
        censor(comment)

        # Assert
        self.assertTrue(Review.all_objects.filter(id=review.id).exists())
        review = Review.all_objects.get(id=review.id)
        self.assertTrue(review.is_removed)
        self.assertFalse(review.is_public)
