import uuid

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from feed.models import FeedEntry
from hub.models import Hub
from paper.models import Paper
from user.views.follow_view_mixins import create_follow

User = get_user_model()


class FeedViewSetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password=uuid.uuid4().hex
        )
        self.paper = Paper.objects.create(
            title="Test Paper",
        )
        self.hub = Hub.objects.create(
            name="Test Hub",
        )
        self.paper.hubs.add(self.hub)

        # Set up API client
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.user_content_type = ContentType.objects.get_for_model(User)
        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        self.hub_content_type = ContentType.objects.get_for_model(Hub)

        create_follow(self.user, self.hub)

        FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=self.paper.paper_publish_date,
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            parent_content_type=self.hub_content_type,
            parent_object_id=self.hub.id,
        )

    def test_feed_returns_followed_items(self):
        """Test that feed only returns items from followed users"""
        url = reverse("feed-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_feed_pagination(self):
        """Test feed pagination"""
        for i in range(25):
            paper = Paper.objects.create(
                title=f"Test Paper {i}",
            )
            FeedEntry.objects.create(
                user=self.user,
                action="PUBLISH",
                action_date=paper.paper_publish_date,
                content_type=self.paper_content_type,
                object_id=paper.id,
                parent_content_type=self.hub_content_type,
                parent_object_id=self.hub.id,
            )

        url = reverse("feed-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 20)
        self.assertIsNotNone(response.data["next"])
        self.assertIsNone(response.data["previous"])

    def test_custom_page_size(self):
        """Test custom page size parameter"""
        paper2 = Paper.objects.create(
            title="Test Paper 2",
        )
        paper2.hubs.add(self.hub)
        FeedEntry.objects.create(
            user=self.user,
            action="PUBLISH",
            action_date=paper2.paper_publish_date,
            content_type=self.paper_content_type,
            object_id=paper2.id,
            parent_content_type=self.hub_content_type,
            parent_object_id=self.hub.id,
        )

        url = reverse("feed-list")
        response = self.client.get(url, {"page_size": 2})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)
