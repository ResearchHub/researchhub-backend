"""
Tests for ExportService.
"""

import csv
import tempfile
from datetime import datetime
from unittest.mock import patch

from django.test import TestCase

from analytics.constants.event_types import FEED_ITEM_IMPRESSION
from analytics.models import UserInteractions
from personalize.config.constants import CSV_HEADERS
from personalize.services.export_service import ExportService
from personalize.tests.helpers import (
    create_prefetched_grant,
    create_prefetched_paper,
    create_prefetched_post,
    create_prefetched_proposal,
)
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    QUESTION,
)
from user.tests.helpers import create_random_default_user


class ExportItemsIteratorTests(TestCase):
    """Tests for export_items method."""

    def test_export_items_yields_all_documents(self):
        """export_items should yield row dict for each document."""
        # Arrange
        doc1 = create_prefetched_paper(title="Paper 1")
        doc2 = create_prefetched_paper(title="Paper 2")
        queryset = (
            ResearchhubUnifiedDocument.objects.filter(id__in=[doc1.id, doc2.id])
            .select_related("paper")
            .prefetch_related(
                "hubs",
                "related_bounties",
                "fundraises",
                "grants",
                "paper__authorships__author",
                "posts__authors",
            )
        )
        service = ExportService(chunk_size=10)

        # Act
        items = list(service.export_items(queryset))

        # Assert
        self.assertEqual(len(items), 2)
        self.assertIn("ITEM_ID", items[0])
        self.assertIn("ITEM_ID", items[1])

    def test_export_items_processes_in_chunks(self):
        """export_items should process documents in specified chunk_size."""
        # Arrange
        docs = [create_prefetched_paper(title=f"Paper {i}") for i in range(5)]
        doc_ids = [doc.id for doc in docs]
        queryset = (
            ResearchhubUnifiedDocument.objects.filter(id__in=doc_ids)
            .select_related("paper")
            .prefetch_related(
                "hubs",
                "related_bounties",
                "fundraises",
                "grants",
                "paper__authorships__author",
                "posts__authors",
            )
        )
        service = ExportService(chunk_size=2)

        # Act
        items = list(service.export_items(queryset))

        # Assert
        self.assertEqual(len(items), 5)

    def test_export_items_handles_empty_queryset(self):
        """export_items should handle empty queryset gracefully."""
        # Arrange
        queryset = ResearchhubUnifiedDocument.objects.none()
        service = ExportService(chunk_size=10)

        # Act
        items = list(service.export_items(queryset))

        # Assert
        self.assertEqual(len(items), 0)

    def test_export_items_skips_failed_mappings(self):
        """export_items should continue when individual mapping fails."""
        # Arrange
        doc1 = create_prefetched_paper(title="Paper 1")
        doc2 = create_prefetched_paper(title="Paper 2")
        queryset = (
            ResearchhubUnifiedDocument.objects.filter(id__in=[doc1.id, doc2.id])
            .select_related("paper")
            .prefetch_related(
                "hubs",
                "related_bounties",
                "fundraises",
                "grants",
                "paper__authorships__author",
                "posts__authors",
            )
        )
        service = ExportService(chunk_size=10)

        # Act
        with patch.object(
            service.mapper,
            "map_to_csv_item",
            side_effect=[Exception("Error"), {"ITEM_ID": "123"}],
        ):
            items = list(service.export_items(queryset))

        # Assert
        self.assertEqual(len(items), 1)


class ExportToCSVTests(TestCase):
    """Tests for export_to_csv method."""

    def test_export_to_csv_creates_file_with_headers(self):
        """export_to_csv should create CSV with correct headers."""
        # Arrange
        doc = create_prefetched_paper()
        queryset = (
            ResearchhubUnifiedDocument.objects.filter(id=doc.id)
            .select_related("paper")
            .prefetch_related(
                "hubs",
                "related_bounties",
                "fundraises",
                "grants",
                "paper__authorships__author",
                "posts__authors",
            )
        )
        service = ExportService(chunk_size=10)

        # Act
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".csv") as f:
            filename = f.name
            result = service.export_to_csv(queryset, filename)

            # Read back the file
            with open(filename, "r", encoding="utf-8") as csvfile:
                reader = csv.DictReader(csvfile)
                headers = reader.fieldnames

        # Assert
        self.assertEqual(headers, CSV_HEADERS)
        self.assertEqual(result["exported"], 1)
        self.assertEqual(result["csv_errors"], 0)
        self.assertEqual(result["failed_ids"], [])
        self.assertEqual(result["filtered_by_date_ids"], [])

    def test_export_to_csv_returns_correct_counts(self):
        """Should return dict with all count fields."""
        # Arrange
        docs = [create_prefetched_paper(title=f"Paper {i}") for i in range(3)]
        doc_ids = [doc.id for doc in docs]
        queryset = (
            ResearchhubUnifiedDocument.objects.filter(id__in=doc_ids)
            .select_related("paper")
            .prefetch_related(
                "hubs",
                "related_bounties",
                "fundraises",
                "grants",
                "paper__authorships__author",
                "posts__authors",
            )
        )
        service = ExportService(chunk_size=10)

        # Act
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".csv") as f:
            filename = f.name
            result = service.export_to_csv(queryset, filename)

        # Assert
        self.assertEqual(result["exported"], 3)
        self.assertEqual(result["csv_errors"], 0)
        self.assertEqual(result["failed_ids"], [])
        self.assertEqual(result["filtered_by_date_ids"], [])

    def test_export_to_csv_handles_write_errors_gracefully(self):
        """Should handle errors during export gracefully."""
        # Arrange
        doc = create_prefetched_paper(title="Paper")
        queryset = (
            ResearchhubUnifiedDocument.objects.filter(id=doc.id)
            .select_related("paper")
            .prefetch_related(
                "hubs",
                "related_bounties",
                "fundraises",
                "grants",
                "paper__authorships__author",
                "posts__authors",
            )
        )
        service = ExportService(chunk_size=10)

        # Act
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".csv") as f:
            filename = f.name
            result = service.export_to_csv(queryset, filename)

        # Assert - export should work without errors
        self.assertEqual(result["exported"], 1)
        self.assertEqual(result["csv_errors"], 0)
        self.assertEqual(result["failed_ids"], [])
        self.assertEqual(result["filtered_by_date_ids"], [])

    def test_export_to_csv_with_multiple_chunks(self):
        """Should correctly export across multiple chunks."""
        # Arrange
        docs = [create_prefetched_paper(title=f"Paper {i}") for i in range(5)]
        doc_ids = [doc.id for doc in docs]
        queryset = (
            ResearchhubUnifiedDocument.objects.filter(id__in=doc_ids)
            .select_related("paper")
            .prefetch_related(
                "hubs",
                "related_bounties",
                "fundraises",
                "grants",
                "paper__authorships__author",
                "posts__authors",
            )
        )
        service = ExportService(chunk_size=2)

        # Act
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".csv") as f:
            filename = f.name
            result = service.export_to_csv(queryset, filename)

        # Assert
        self.assertEqual(result["exported"], 5)
        self.assertEqual(result["csv_errors"], 0)
        self.assertEqual(result["failed_ids"], [])
        self.assertEqual(result["filtered_by_date_ids"], [])


class IntegrationTests(TestCase):
    """Integration tests for export service."""

    def test_full_export_with_all_document_types(self):
        """Integration test with papers, posts, grants, proposals."""
        # Arrange
        paper = create_prefetched_paper(title="Test Paper")
        grant = create_prefetched_grant(title="Test Grant")
        proposal = create_prefetched_proposal(title="Test Proposal")
        discussion = create_prefetched_post(
            title="Test Discussion", document_type=DISCUSSION
        )
        question = create_prefetched_post(title="Test Question", document_type=QUESTION)

        doc_ids = [paper.id, grant.id, proposal.id, discussion.id, question.id]
        queryset = (
            ResearchhubUnifiedDocument.objects.filter(id__in=doc_ids)
            .select_related("paper")
            .prefetch_related(
                "hubs",
                "related_bounties",
                "fundraises",
                "grants",
                "paper__authorships__author",
                "posts__authors",
            )
        )
        service = ExportService(chunk_size=10)

        # Act
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".csv") as f:
            filename = f.name
            result = service.export_to_csv(queryset, filename)

            # Read back the file
            with open(filename, "r", encoding="utf-8") as csvfile:
                reader = csv.DictReader(csvfile)
                rows = list(reader)

        # Assert
        self.assertEqual(result["exported"], 5)
        self.assertEqual(result["failed_ids"], [])
        self.assertEqual(len(rows), 5)
        item_types = {row["ITEM_TYPE"] for row in rows}
        # Check for mapped ITEM_TYPE values
        self.assertIn("PAPER", item_types)
        self.assertIn("RFP", item_types)  # GRANT maps to RFP
        self.assertIn("PROPOSAL", item_types)  # PREREGISTRATION maps to PROPOSAL
        self.assertIn("POST", item_types)  # DISCUSSION maps to POST
        self.assertIn("QUESTION", item_types)

    def test_export_with_batch_data_integration(self):
        """Verify batch queries are called correctly."""
        # Arrange
        doc = create_prefetched_paper()
        queryset = (
            ResearchhubUnifiedDocument.objects.filter(id=doc.id)
            .select_related("paper")
            .prefetch_related(
                "hubs",
                "related_bounties",
                "fundraises",
                "grants",
                "paper__authorships__author",
                "posts__authors",
            )
        )
        service = ExportService(chunk_size=10)

        # Act
        items = list(service.export_items(queryset))

        # Assert
        self.assertEqual(len(items), 1)
        self.assertIn("HAS_ACTIVE_BOUNTY", items[0])
        self.assertIn("PROPOSAL_IS_OPEN", items[0])
        self.assertIn("RFP_IS_OPEN", items[0])

    def test_export_includes_feed_item_impression_events(self):
        """Test that documents with FEED_ITEM_IMPRESSION events are exported."""
        # Arrange
        user = create_random_default_user("impression_test_user")
        doc = create_prefetched_paper(title="Paper with Impression")

        # Create a FEED_ITEM_IMPRESSION interaction
        UserInteractions.objects.create(
            user=user,
            event=FEED_ITEM_IMPRESSION,
            unified_document=doc,
            content_type=None,
            object_id=None,
            event_timestamp=datetime.now(),
            is_synced_with_personalize=False,
            personalize_rec_id="test-rec-id",
        )

        queryset = (
            ResearchhubUnifiedDocument.objects.filter(id=doc.id)
            .select_related("paper")
            .prefetch_related(
                "hubs",
                "related_bounties",
                "fundraises",
                "grants",
                "paper__authorships__author",
            )
        )
        service = ExportService(chunk_size=10)

        # Act
        items = list(service.export_items(queryset))

        # Assert
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["ITEM_ID"], str(doc.id))
        self.assertIn("TITLE", items[0])
