import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from discussion.models import Vote
from feed.models import FeedEntry
from hub.models import Hub
from paper.models import Paper
from researchhub_comment.constants import rh_comment_thread_types
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.views.follow_view_mixins import create_follow

User = get_user_model()


class FeedViewSetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password=uuid.uuid4().hex
        )
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.paper = Paper.objects.create(
            title="Test Paper",
            paper_publish_date=timezone.now(),
            unified_document=self.unified_document,
        )
        self.post_unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="POST"
        )
        self.post = ResearchhubPost.objects.create(
            title="Test Post",
            document_type="POST",
            created_by=self.user,
            unified_document=self.post_unified_document,
            score=5,
            discussion_count=3,
        )
        self.hub = Hub.objects.create(
            name="Test Hub",
        )
        self.unified_document.hubs.add(self.hub)

        # Set up API client
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.user_content_type = ContentType.objects.get_for_model(User)
        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        self.post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

        create_follow(self.user, self.hub)

        # Create initial feed entry
        self.feed_entry = FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=self.paper.paper_publish_date,
            content_type=self.paper_content_type,
            metrics={"votes": 100, "comments": 10},
            object_id=self.paper.id,
            unified_document=self.paper.unified_document,
        )
        self.feed_entry.hubs.add(self.hub)

        # Create another user and their content for testing
        self.other_user = User.objects.create_user(
            username="otheruser", password=uuid.uuid4().hex
        )
        self.other_hub = Hub.objects.create(name="Other Hub")
        self.other_paper = Paper.objects.create(
            title="Other Paper",
            paper_publish_date=timezone.now(),
        )
        self.other_paper.hubs.add(self.other_hub)

        # Create feed entry for other user's content
        self.other_feed_entry = FeedEntry.objects.create(
            user=self.other_user,
            action="PUBLISH",
            action_date=self.other_paper.paper_publish_date,
            content_type=self.paper_content_type,
            metrics={"votes": 100, "comments": 10},
            object_id=self.other_paper.id,
            unified_document=self.other_paper.unified_document,
        )
        self.other_feed_entry.hubs.add(self.other_hub)

        self.post_feed_entry = FeedEntry.objects.create(
            user=self.other_user,
            action="PUBLISH",
            action_date=self.post.created_date,
            content_type=self.post_content_type,
            metrics={"votes": 100, "comments": 10},
            object_id=self.post.id,
            unified_document=self.post.unified_document,
        )
        self.post_feed_entry.hubs.add(self.other_hub)

        cache.clear()

    def test_default_feed_view(self):
        """Test that default feed view (latest) returns all items"""
        url = reverse("feed-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 3)

    @patch("feed.views.feed_view.cache")
    def test_default_feed_view_cache(self, mock_cache):
        # No cache on first request
        mock_cache.get.return_value = None

        url = reverse("feed-list")
        response = self.client.get(url)

        self.assertTrue(mock_cache.get.called)
        self.assertTrue(mock_cache.set.called)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 3)

        # Return a "cached" response on second request
        mock_cache.get.return_value = mock_cache.set.call_args[0][1]
        mock_cache.set.reset_mock()

        response2 = self.client.get(url)

        self.assertTrue(mock_cache.get.called)
        self.assertFalse(mock_cache.set.called)

        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response2.data["results"]), 3)
        self.assertEqual(response.data["results"], response2.data["results"])

    def test_feed_pagination(self):
        """Test feed pagination"""
        for i in range(25):
            unified_doc = ResearchhubUnifiedDocument.objects.create(
                document_type="PAPER"
            )
            paper = Paper.objects.create(
                title=f"Test Paper {i}",
                paper_publish_date=timezone.now(),
                unified_document=unified_doc,
            )
            unified_doc.hubs.add(self.hub)
            FeedEntry.objects.create(
                user=self.user,
                action="PUBLISH",
                action_date=paper.paper_publish_date,
                content_type=self.paper_content_type,
                object_id=paper.id,
                unified_document=paper.unified_document,
            )

        url = reverse("feed-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 20)
        self.assertIsNotNone(response.data["next"])
        self.assertIsNone(response.data["previous"])

    def test_custom_page_size(self):
        """Test custom page size parameter"""
        # Arrange
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        paper2 = Paper.objects.create(
            title="Test Paper 2",
            paper_publish_date=timezone.now(),
            unified_document=unified_doc,
        )
        unified_doc.hubs.add(self.hub)
        FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=paper2.paper_publish_date,
            content_type=self.paper_content_type,
            object_id=paper2.id,
            unified_document=paper2.unified_document,
        )

        url = reverse("feed-list")

        # Act
        response = self.client.get(url, {"page_size": 2})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

    def test_latest_feed_view(self):
        """Test that latest feed view shows all items regardless of following status"""
        url = reverse("feed-list")
        response = self.client.get(url, {"feed_view": "latest"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should see both followed and unfollowed content
        self.assertEqual(len(response.data["results"]), 3)

    def test_following_feed_view(self):
        """Test that following feed view only shows items from followed entities"""
        url = reverse("feed-list")
        response = self.client.get(url, {"feed_view": "following"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only see followed content
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], self.paper.id
        )

    def test_hub_filter(self):
        """Test filtering feed by hub"""
        url = reverse("feed-list")
        response = self.client.get(url, {"hub_slug": self.hub.slug})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only see content from specified hub
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], self.paper.id
        )

    def test_following_feed_with_no_follows(self):
        """Test that following feed shows latest content when user has no follows"""
        # Remove all follows
        self.user.following.all().delete()

        url = reverse("feed-list")
        response = self.client.get(url, {"feed_view": "following"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should see all content since user has no follows
        self.assertEqual(len(response.data["results"]), 3)

    def test_popular_feed_view(self):
        """Test that popular feed view sorts by hot_score"""
        high_score_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", hot_score=100
        )
        medium_score_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", hot_score=50
        )
        low_score_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", hot_score=10
        )

        high_score_paper = Paper.objects.create(
            title="High Score Paper",
            paper_publish_date=timezone.now(),
            unified_document=high_score_doc,
        )
        medium_score_paper = Paper.objects.create(
            title="Medium Score Paper",
            paper_publish_date=timezone.now(),
            unified_document=medium_score_doc,
        )
        low_score_paper = Paper.objects.create(
            title="Low Score Paper",
            paper_publish_date=timezone.now(),
            unified_document=low_score_doc,
        )

        high_score_doc.hubs.add(self.hub)
        medium_score_doc.hubs.add(self.hub)
        low_score_doc.hubs.add(self.hub)

        # Create feed entries for each paper
        FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=high_score_paper.id,
            unified_document=high_score_doc,
            hot_score=high_score_doc.hot_score,
        )
        FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=medium_score_paper.id,
            unified_document=medium_score_doc,
            hot_score=medium_score_doc.hot_score,
        )
        FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=low_score_paper.id,
            unified_document=low_score_doc,
            hot_score=low_score_doc.hot_score,
        )

        url = reverse("feed-list")
        response = self.client.get(url, {"feed_view": "popular"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data["results"]
        self.assertEqual(len(results), 6)

        content_object_ids = [result["content_object"]["id"] for result in results]
        self.assertEqual(content_object_ids[0], high_score_paper.id)
        self.assertEqual(content_object_ids[1], medium_score_paper.id)
        self.assertEqual(content_object_ids[2], low_score_paper.id)

    def test_popular_feed_view_with_hub_filter(self):
        """Test that popular feed view works with hub filter"""
        high_score_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", hot_score=100
        )

        another_hub = Hub.objects.create(name="Another Hub")

        high_score_paper = Paper.objects.create(
            title="High Score Paper",
            paper_publish_date=timezone.now(),
            unified_document=high_score_doc,
        )

        high_score_doc.hubs.add(another_hub)

        feed_entry = FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=high_score_paper.id,
            unified_document=high_score_doc,
        )
        feed_entry.hubs.add(another_hub)

        url = reverse("feed-list")
        response = self.client.get(
            url, {"feed_view": "popular", "hub_slug": self.hub.slug}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should not include the high_score_paper since it's not in self.hub
        results = response.data["results"]
        content_object_ids = [result["content_object"]["id"] for result in results]
        self.assertNotIn(high_score_paper.id, content_object_ids)

        # Test with the new hub filter
        response = self.client.get(
            url, {"feed_view": "popular", "hub_slug": another_hub.slug}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should include the high_score_paper since it's in another_hub
        results = response.data["results"]
        content_object_ids = [result["content_object"]["id"] for result in results]
        self.assertIn(high_score_paper.id, content_object_ids)

    def test_feed_includes_user_votes(self):
        """Test that feed response includes user votes"""
        # Arrange
        post = ResearchhubPost.objects.create(
            title="Test Post",
            document_type="POST",
            created_by=self.user,
            unified_document=self.unified_document,
            score=5,  # Add score for metrics testing
            discussion_count=3,  # Add discussion_count for metrics testing
        )

        paper_thread = RhCommentThreadModel.objects.create(
            thread_type=rh_comment_thread_types.GENERIC_COMMENT,
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            created_by=self.user,
        )

        comment = RhCommentModel.objects.create(
            thread=paper_thread,
            created_by=self.user,
            comment_content_json={"ops": [{"insert": "Test comment"}]},
        )

        FeedEntry.objects.create(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=post.id,
            item=post,
            created_date=timezone.now(),
            action="PUBLISH",
            action_date=timezone.now(),
            metrics={"votes": 100, "comments": 10},
            user=self.user,
            unified_document=self.unified_document,
        )

        FeedEntry.objects.create(
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=comment.id,
            item=comment,
            created_date=timezone.now(),
            action="PUBLISH",
            action_date=timezone.now(),
            metrics={"votes": 100, "comments": 10},
            user=self.user,
            unified_document=self.unified_document,
        )

        Vote.objects.create(
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            created_by=self.user,
            vote_type=Vote.UPVOTE,
        )

        Vote.objects.create(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=post.id,
            created_by=self.user,
            vote_type=Vote.UPVOTE,
        )

        Vote.objects.create(
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=comment.id,
            created_by=self.user,
            vote_type=Vote.UPVOTE,
        )

        Vote.objects.create(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=self.post.id,
            created_by=self.user,
            vote_type=Vote.UPVOTE,
        )

        feed_entries = FeedEntry.objects.all()
        self.assertEqual(feed_entries.count(), 5)

        # Act
        url = reverse("feed-list")
        response = self.client.get(url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        for item in response.data.get("results", []):
            if (
                str(item.get("content_object").get("id")) == str(self.paper.id)
                or item.get("content_type") != "PAPER"
            ):
                self.assertIn("user_vote", item)
                self.assertIn("metrics", item)
                self.assertIn("votes", item["metrics"])
                if (
                    item.get("content_type") == "RESEARCHHUBPOST"
                    or item.get("content_type") == "PAPER"
                ):
                    self.assertIn("comments", item["metrics"])

    @patch("feed.views.feed_view.cache")
    def test_user_votes_with_cached_response(self, mock_cache):
        """Test that user votes are added to both cached and non-cached responses"""
        # Create a test user and authenticate
        test_user = User.objects.create_user(
            username="voteuser", password="testpassword"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=test_user)

        # Create a post
        post = ResearchhubPost.objects.create(
            title="Vote Test Post",
            document_type="POST",
            created_by=self.user,
            unified_document=self.unified_document,
        )

        # Create a feed entry for the post
        FeedEntry.objects.create(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=post.id,
            item=post,
            created_date=timezone.now(),
            action="PUBLISH",
            action_date=timezone.now(),
            user=self.user,
            unified_document=self.unified_document,
        )

        # Create a vote for the post by the test user
        post_vote = Vote.objects.create(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=post.id,
            created_by=test_user,
            vote_type=Vote.UPVOTE,
        )

        # First request - no cache
        mock_cache.get.return_value = None
        url = reverse("feed-list")
        response1 = self.client.get(url)

        # Verify the response includes the user vote
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        # Find the post in the response
        post_item = None
        for item in response1.data.get("results", []):
            if item.get("content_type") == "RESEARCHHUBPOST" and str(
                item["content_object"].get("id")
            ) == str(post.id):
                post_item = item
                break

        self.assertIsNotNone(post_item, "Post should be in the feed")
        self.assertIn("user_vote", post_item)

        # Verify the vote data is correct
        user_vote = post_item["user_vote"]
        self.assertEqual(user_vote["vote_type"], Vote.UPVOTE)

        # Store what was cached (should be without votes)
        cached_data = mock_cache.set.call_args[0][1]

        # Update the vote to verify fresh votes are fetched
        post_vote.vote_type = Vote.DOWNVOTE  # Change from upvote to downvote
        post_vote.save()

        # Second request - use cached response
        mock_cache.get.return_value = cached_data
        mock_cache.set.reset_mock()

        response2 = self.client.get(url)

        # Verify the response includes the updated user vote
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

        # Find the post in the response
        post_item = None
        for item in response2.data.get("results", []):
            if item.get("content_type") == "RESEARCHHUBPOST" and str(
                item["content_object"].get("id")
            ) == str(post.id):
                post_item = item
                break

        self.assertIsNotNone(post_item, "Post should be in the feed")
        self.assertIn("user_vote", post_item)

        # Verify the vote data is updated (should be a downvote now)
        user_vote = post_item["user_vote"]
        self.assertEqual(user_vote["vote_type"], Vote.DOWNVOTE)

        # Verify cache was used but not updated
        self.assertTrue(mock_cache.get.called)
        self.assertFalse(mock_cache.set.called)

    def test_distinct_entries_in_latest_feed(self):
        """Test that latest feed view returns entries ordered by action_date.
        Multiple entries for the same item can appear if they have different actions."""
        # Create multiple feed entries for the same paper
        newer_entry = FeedEntry.objects.create(
            user=self.user,
            action="COMMENT",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            unified_document=self.unified_document,
        )

        # Create another entry for the same paper but with an older date and
        # different action
        # Using OPEN action to avoid unique constraint violation
        older_entry = FeedEntry.objects.create(
            user=self.user,
            action="OPEN",
            action_date=timezone.now() - timezone.timedelta(days=5),
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            unified_document=self.unified_document,
        )

        url = reverse("feed-list")
        response = self.client.get(url, {"feed_view": "latest"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Extract the IDs of the content objects in the results
        results = response.data["results"]
        result_pairs = [(r["content_type"], r["content_object"]["id"]) for r in results]

        # Count occurrences of the paper's content type and ID
        paper_pair = (self.paper_content_type.model.upper(), self.paper.id)
        paper_occurrences = result_pairs.count(paper_pair)

        # There should be 3 occurrences of the paper (one from setUp, plus two we just created)
        error_msg = f"Expected 3 occurrences of paper, got {paper_occurrences}"
        self.assertEqual(paper_occurrences, 3, error_msg)

        # Verify entries are ordered by action_date descending
        paper_results = [
            r for r in results if r["content_object"]["id"] == self.paper.id
        ]
        # The first one should be the newest entry (COMMENT action)
        self.assertEqual(
            paper_results[0]["action"],
            newer_entry.action,
            "The first entry should be the newest one",
        )

    def test_distinct_entries_in_popular_feed(self):
        """Test that popular feed view returns only the most recent entry for each
        content type and object ID."""
        # Set hot score for the unified document
        self.unified_document.hot_score = 100
        self.unified_document.save()

        # Create multiple feed entries for the same paper with different dates
        # and actions
        _ = FeedEntry.objects.create(
            user=self.user,
            action="OPEN",
            action_date=timezone.now() - timezone.timedelta(days=5),
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            unified_document=self.unified_document,
        )

        newer_entry = FeedEntry.objects.create(
            user=self.user,
            action="COMMENT",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            unified_document=self.unified_document,
        )

        url = reverse("feed-list")
        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Extract the IDs of the content objects in the results
        results = response.data["results"]
        result_pairs = [(r["content_type"], r["content_object"]["id"]) for r in results]

        # Count occurrences of the paper's content type and ID
        paper_pair = (self.paper_content_type.model.upper(), self.paper.id)
        paper_occurrences = result_pairs.count(paper_pair)

        # There should be only one occurrence of the paper (the newest entry)
        error_msg = f"Expected 1 occurrence of paper, got {paper_occurrences}"
        self.assertEqual(paper_occurrences, 1, error_msg)

        # Find the paper result and verify it's the newer entry
        paper_result = next(
            r for r in results if r["content_object"]["id"] == self.paper.id
        )
        self.assertEqual(
            paper_result["action"],
            newer_entry.action,
            "The entry in the results should be the newest one",
        )

    def test_source_researchhub(self):
        """
        Test that the source filter only returns items from ResearchHub.
        These are currently all items that are not papers.
        """
        # Arrange
        url = reverse("feed-list")

        # Act
        response = self.client.get(url, {"source": "researchhub"})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        for item in response.data["results"]:
            self.assertNotEqual(item["content_type"], "PAPER")

    def test_source_all(self):
        """Test that the source filter returns all items."""
        # Arrange
        url = reverse("feed-list")

        # Act
        response = self.client.get(url, {"source": "all"})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 3)

    def test_following_feed_with_hot_score_sorting(self):
        """Test that following feed can be sorted by hot_score and only shows papers/posts"""
        # Arrange
        # Create papers with different hot_scores in followed hub
        high_score_paper = Paper.objects.create(
            title="High Score Paper",
            paper_publish_date=timezone.now(),
        )
        high_score_paper.hubs.add(self.hub)

        low_score_paper = Paper.objects.create(
            title="Low Score Paper",
            paper_publish_date=timezone.now(),
        )
        low_score_paper.hubs.add(self.hub)

        # Create a comment in the followed hub (should be excluded with hot_score sorting)
        comment_thread = RhCommentThreadModel.objects.create(
            thread_type=rh_comment_thread_types.GENERIC_COMMENT,
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            created_by=self.user,
        )
        comment = RhCommentModel.objects.create(
            thread=comment_thread,
            comment_content_json={"ops": [{"insert": "Test comment"}]},
            comment_content_type="QUILL_EDITOR",
            created_by=self.user,
        )
        comment_content_type = ContentType.objects.get_for_model(RhCommentModel)

        # Create feed entry for the comment with high hot_score
        comment_entry = FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=comment_content_type,
            object_id=comment.id,
            unified_document=self.paper.unified_document,
            hot_score=2000,  # Higher than papers
            metrics={"votes": 1000, "comments": 100},
        )
        comment_entry.hubs.add(self.hub)

        # Create feed entries with different hot_scores
        high_score_entry = FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=high_score_paper.id,
            unified_document=high_score_paper.unified_document,
            hot_score=1000,
            metrics={"votes": 500, "comments": 50},
        )
        high_score_entry.hubs.add(self.hub)

        low_score_entry = FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=low_score_paper.id,
            unified_document=low_score_paper.unified_document,
            hot_score=10,
            metrics={"votes": 5, "comments": 1},
        )
        low_score_entry.hubs.add(self.hub)

        # Update the existing feed entry to have a medium hot_score
        self.feed_entry.hot_score = 100
        self.feed_entry.save()

        # Refresh materialized views
        cache.clear()

        url = reverse("feed-list")

        # Act - Get following feed with hot_score sorting
        response = self.client.get(
            url, {"feed_view": "following", "sort_by": "hot_score"}
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]

        # Should only see content from followed hub
        self.assertGreater(len(results), 0)

        # Verify that only papers and posts are included (no comments)
        for item in results:
            self.assertIn(
                item["content_type"],
                ["PAPER", "POST"],
                f"Following feed with hot_score should only show papers and posts, "
                f"but found {item['content_type']}",
            )

        # Verify items are sorted by hot_score (descending)
        hot_scores = []
        for i, item in enumerate(results):
            # Get the corresponding feed entry to check hot_score
            content_id = item["content_object"]["id"]
            content_type = item["content_type"]

            if content_type == "PAPER":
                entry = FeedEntry.objects.filter(
                    object_id=content_id, content_type=self.paper_content_type
                ).first()
                if entry:
                    hot_scores.append(entry.hot_score)
            elif content_type == "POST":
                entry = FeedEntry.objects.filter(
                    object_id=content_id, content_type=self.post_content_type
                ).first()
                if entry:
                    hot_scores.append(entry.hot_score)

        # Check that hot_scores are in descending order
        for i in range(len(hot_scores) - 1):
            self.assertGreaterEqual(
                hot_scores[i],
                hot_scores[i + 1],
                f"Feed items not sorted by hot_score: {hot_scores}",
            )

        # Ensure cache key includes sort_by parameter
        cache_key = response.headers.get("RH-Cache")
        if cache_key == "miss":
            # Make another request to test cache hit
            response2 = self.client.get(
                url, {"feed_view": "following", "sort_by": "hot_score"}
            )
            self.assertEqual(response2.headers.get("RH-Cache"), "hit (auth)")

    def test_following_feed_default_sorting(self):
        """Test that following feed defaults to latest sorting when not specified"""
        url = reverse("feed-list")

        # Act - Get following feed without sort_by parameter
        response = self.client.get(url, {"feed_view": "following"})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should use FeedEntryLatest by default
        # Verify by checking that entries are sorted by action_date
        results = response.data["results"]
        if len(results) > 1:
            dates = []
            for item in results:
                if "action_date" in item:
                    dates.append(item["action_date"])

            # Check that dates are in descending order
            for i in range(len(dates) - 1):
                self.assertGreaterEqual(
                    dates[i],
                    dates[i + 1],
                    "Feed items not sorted by action_date when using default sort",
                )
