from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from paper.tests.helpers import create_paper
from researchhub_comment.models import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.models import Action
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
