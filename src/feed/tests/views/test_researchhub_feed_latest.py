from datetime import timedelta
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from feed.models import FeedEntry
from hub.models import Hub
from paper.models import Paper
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_default_user


class LatestFeedTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = create_random_default_user("latest_test_user")

        self.hub, _ = Hub.objects.get_or_create(
            slug="biorxiv", defaults={"name": "bioRxiv"}
        )

        self.paper_content_type = ContentType.objects.get_for_model(Paper)

        # Create papers with different action dates
        now = timezone.now()

        # Newest paper
        self.newest_paper_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.newest_paper_doc.hubs.add(self.hub)
        self.newest_paper = Paper.objects.create(
            title="Newest Paper",
            paper_publish_date=now,
            unified_document=self.newest_paper_doc,
        )
        self.newest_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=now,
            content_type=self.paper_content_type,
            object_id=self.newest_paper.id,
            unified_document=self.newest_paper_doc,
            hot_score=10,
            hot_score_v2=10,
            content={},
            metrics={},
        )
        self.newest_entry.hubs.add(self.hub)

        # Older paper
        self.older_paper_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.older_paper_doc.hubs.add(self.hub)
        self.older_paper = Paper.objects.create(
            title="Older Paper",
            paper_publish_date=now - timedelta(days=1),
            unified_document=self.older_paper_doc,
        )
        self.older_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=now - timedelta(days=1),
            content_type=self.paper_content_type,
            object_id=self.older_paper.id,
            unified_document=self.older_paper_doc,
            hot_score=100,  # Higher score but older
            hot_score_v2=100,
            content={},
            metrics={},
        )
        self.older_entry.hubs.add(self.hub)

    def tearDown(self):
        cache.clear()

    def test_latest_feed_returns_results_ordered_by_action_date(self):
        """Test that latest feed returns results sorted by action_date descending."""
        url = reverse("feed-list")

        response = self.client.get(url, {"feed_view": "latest"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertGreaterEqual(len(results), 2)

        # Verify newest paper comes first (even though it has lower hot_score)
        result_ids = [r["content_object"]["id"] for r in results]
        newest_idx = result_ids.index(self.newest_paper.id)
        older_idx = result_ids.index(self.older_paper.id)
        self.assertLess(newest_idx, older_idx)

        # Verify ordering by action_date (newest first)
        if len(results) >= 2:
            first_date = results[0].get("action_date")
            second_date = results[1].get("action_date")
            self.assertGreaterEqual(first_date, second_date)

    @patch("feed.views.feed_view.cache")
    def test_latest_feed_uses_cache(self, mock_cache):
        """Test that latest feed respects use_cache config."""
        url = reverse("feed-list")
        mock_cache.get.return_value = None

        self.client.get(url, {"feed_view": "latest"})

        # Verify cache was checked and set
        self.assertTrue(mock_cache.get.called)
        self.assertTrue(mock_cache.set.called)

    def _create_paper_with_feed_entry(self, title, hubs):
        """Helper to create a paper with associated feed entry and hubs."""
        doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        doc.hubs.add(*hubs)
        paper = Paper.objects.create(
            title=title,
            paper_publish_date=timezone.now(),
            unified_document=doc,
        )
        entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=paper.id,
            unified_document=doc,
            content={},
            metrics={},
        )
        entry.hubs.add(*hubs)
        return paper

    def test_latest_without_hub_slug_returns_only_preprint_hub_papers(self):
        """Latest feed without hub_slug only returns papers from preprint hubs."""
        biorxiv_hub, _ = Hub.objects.get_or_create(
            slug="biorxiv", defaults={"name": "bioRxiv"}
        )
        other_hub, _ = Hub.objects.get_or_create(
            slug="other-hub", defaults={"name": "Other"}
        )

        preprint = self._create_paper_with_feed_entry("Preprint", [biorxiv_hub])
        non_preprint = self._create_paper_with_feed_entry("Non-Preprint", [other_hub])

        response = self.client.get(reverse("feed-list"), {"feed_view": "latest"})

        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        self.assertIn(preprint.id, result_ids)
        self.assertNotIn(non_preprint.id, result_ids)

    def test_latest_with_hub_slug_bypasses_preprint_restriction(self):
        """Latest feed with hub_slug returns papers from that hub (no restriction)."""
        other_hub, _ = Hub.objects.get_or_create(
            slug="other-hub", defaults={"name": "Other"}
        )
        paper = self._create_paper_with_feed_entry("Other Paper", [other_hub])

        response = self.client.get(
            reverse("feed-list"), {"feed_view": "latest", "hub_slug": "other-hub"}
        )

        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        self.assertIn(paper.id, result_ids)
