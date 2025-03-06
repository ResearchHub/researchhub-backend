import uuid

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from feed.models import FeedEntry
from feed.views import FeedViewSet
from hub.models import Hub
from paper.models import Paper
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
        self.hub = Hub.objects.create(
            name="Test Hub",
        )
        self.unified_document.hubs.add(self.hub)

        # Set up API client
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.user_content_type = ContentType.objects.get_for_model(User)
        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        self.hub_content_type = ContentType.objects.get_for_model(Hub)

        create_follow(self.user, self.hub)

        # Create initial feed entry
        self.feed_entry = FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=self.paper.paper_publish_date,
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            parent_content_type=self.hub_content_type,
            parent_object_id=self.hub.id,
            unified_document=self.paper.unified_document,
        )

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
            object_id=self.other_paper.id,
            parent_content_type=self.hub_content_type,
            parent_object_id=self.other_hub.id,
            unified_document=self.other_paper.unified_document,
        )

    def test_default_feed_view(self):
        """Test that default feed view (latest) returns all items"""
        url = reverse("feed-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

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
                parent_content_type=self.hub_content_type,
                parent_object_id=self.hub.id,
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
            parent_content_type=self.hub_content_type,
            parent_object_id=self.hub.id,
            unified_document=paper2.unified_document,
        )

        url = reverse("feed-list")
        response = self.client.get(url, {"page_size": 2})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

    def test_latest_feed_view(self):
        """Test that latest feed view shows all items regardless of following status"""
        url = reverse("feed-list")
        response = self.client.get(url, {"feed_view": "latest"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should see both followed and unfollowed content
        self.assertEqual(len(response.data["results"]), 2)

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
        self.assertEqual(len(response.data["results"]), 2)

    def test_popular_feed_view(self):
        """Test that popular feed view sorts by unified_document.hot_score"""
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
            parent_content_type=self.hub_content_type,
            parent_object_id=self.hub.id,
            unified_document=high_score_doc,
        )
        FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=medium_score_paper.id,
            parent_content_type=self.hub_content_type,
            parent_object_id=self.hub.id,
            unified_document=medium_score_doc,
        )
        FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=low_score_paper.id,
            parent_content_type=self.hub_content_type,
            parent_object_id=self.hub.id,
            unified_document=low_score_doc,
        )

        url = reverse("feed-list")
        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data["results"]
        self.assertEqual(len(results), 5)

        content_object_ids = [result["content_object"]["id"] for result in results]

        self.assertEqual(content_object_ids[0], high_score_paper.id)
        self.assertEqual(content_object_ids[1], medium_score_paper.id)
        self.assertEqual(content_object_ids[2], low_score_paper.id)

    def test_popular_feed_view_with_multiple_entries(self):
        """Test that popular feed view handles multiple entries per document correctly"""
        # Create a paper with high hot score
        high_score_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", hot_score=100
        )
        high_score_paper = Paper.objects.create(
            title="High Score Paper",
            paper_publish_date=timezone.now(),
            unified_document=high_score_doc,
        )

        high_score_doc.hubs.add(self.hub)

        user2 = User.objects.create_user(
            username="testuser2", email="test2@example.com", password="password123"
        )
        user3 = User.objects.create_user(
            username="testuser3", email="test3@example.com", password="password123"
        )

        FeedEntry.objects.create(
            user=user2,
            action="PUBLISH",
            action_date=timezone.now() - timezone.timedelta(days=10),
            content_type=self.paper_content_type,
            object_id=high_score_paper.id,
            parent_content_type=self.hub_content_type,
            parent_object_id=self.hub.id,
            unified_document=high_score_doc,
        )

        FeedEntry.objects.create(
            user=user3,
            action="PUBLISH",
            action_date=timezone.now() - timezone.timedelta(days=5),
            content_type=self.paper_content_type,
            object_id=high_score_paper.id,
            parent_content_type=self.hub_content_type,
            parent_object_id=self.hub.id,
            unified_document=high_score_doc,
        )

        # Create the most recent entry
        FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=high_score_paper.id,
            parent_content_type=self.hub_content_type,
            parent_object_id=self.hub.id,
            unified_document=high_score_doc,
        )

        url = reverse("feed-list")
        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data["results"]
        content_object_ids = [result["content_object"]["id"] for result in results]

        high_score_paper_count = content_object_ids.count(high_score_paper.id)
        self.assertEqual(
            high_score_paper_count,
            1,
            f"Expected 1 entry for high score paper, got {high_score_paper_count}",
        )

        self.assertIn(
            high_score_paper.id,
            content_object_ids,
            f"High score paper not found in results: {content_object_ids}",
        )

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

        FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=high_score_paper.id,
            parent_content_type=self.hub_content_type,
            parent_object_id=another_hub.id,
            unified_document=high_score_doc,
        )

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

    def test_get_cache_key_popular(self):
        # Act
        cache_key = FeedViewSet._get_cache_key("popular", self.hub.slug, self.user.id)

        # Assert
        self.assertEqual(cache_key, f"feed:popular:{self.hub.slug}")

    def test_get_cache_key_following(self):
        # Act
        cache_key = FeedViewSet._get_cache_key("following", self.hub.slug, self.user.id)

        # Assert
        self.assertEqual(cache_key, f"feed:following:{self.hub.slug}:{self.user.id}")

    def test_get_cache_key_anonymous(self):
        # Act
        cache_key = FeedViewSet._get_cache_key("following", self.hub.slug, None)

        # Assert
        self.assertEqual(cache_key, f"feed:following:{self.hub.slug}:anonymous")
