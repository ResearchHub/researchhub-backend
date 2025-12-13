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


class PdfCopyrightFilteringTests(APITestCase):
    def setUp(self):
        cache.clear()

        self.hub, _ = Hub.objects.get_or_create(
            slug="biorxiv", defaults={"name": "bioRxiv"}
        )
        self.paper_content_type = ContentType.objects.get_for_model(Paper)

        # Paper with display allowed
        self.allowed_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.allowed_doc.hubs.add(self.hub)
        self.allowed_paper = Paper.objects.create(
            title="Allowed Paper",
            paper_publish_date=timezone.now(),
            unified_document=self.allowed_doc,
        )
        self.allowed_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=self.allowed_paper.id,
            unified_document=self.allowed_doc,
            pdf_copyright_allows_display=True,
            content={},
            metrics={},
        )
        self.allowed_entry.hubs.add(self.hub)

        # Paper with display NOT allowed
        self.excluded_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.excluded_doc.hubs.add(self.hub)
        self.excluded_paper = Paper.objects.create(
            title="Excluded Paper",
            paper_publish_date=timezone.now(),
            unified_document=self.excluded_doc,
        )
        self.excluded_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=self.excluded_paper.id,
            unified_document=self.excluded_doc,
            pdf_copyright_allows_display=False,
            content={},
            metrics={},
        )
        self.excluded_entry.hubs.add(self.hub)

    def tearDown(self):
        cache.clear()

    def test_feed_excludes_entries_with_pdf_copyright_disallowed(self):
        """Entries with pdf_copyright_allows_display=False should be excluded."""
        url = reverse("feed-list")

        response = self.client.get(
            url, {"feed_view": "popular", "ordering": "hot_score_v2"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        self.assertNotIn(self.excluded_paper.id, result_ids)

    def test_feed_includes_entries_with_pdf_copyright_allowed(self):
        """Entries with pdf_copyright_allows_display=True should be included."""
        url = reverse("feed-list")

        response = self.client.get(
            url, {"feed_view": "popular", "ordering": "hot_score_v2"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        self.assertIn(self.allowed_paper.id, result_ids)
