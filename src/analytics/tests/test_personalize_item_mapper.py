"""
Unit tests for personalize_item_mapper.

Tests item row mapping for different document types.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from analytics.services.personalize_item_mapper import ItemMapper
from hub.models import Hub
from paper.models import Paper
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from user.models import User


class ItemMapperTest(TestCase):
    """Test ItemMapper class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = ItemMapper()
        self.user = User.objects.create(email="test@example.com", username="testuser")
        self.hub = Hub.objects.create(name="Computer Science", slug="computer-science")

    def test_get_queryset_filters_removed_documents(self):
        """Test that removed documents are filtered out."""
        # Create removed document
        ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=True
        )

        # Create non-removed document
        ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )

        queryset = self.mapper.get_queryset()
        self.assertEqual(queryset.count(), 1)

    def test_get_queryset_excludes_note_type(self):
        """Test that NOTE document type is excluded."""
        # Create NOTE document
        ResearchhubUnifiedDocument.objects.create(
            document_type="NOTE", is_removed=False
        )

        # Create PAPER document
        ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )

        queryset = self.mapper.get_queryset()

        # Should only include PAPER, not NOTE
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().document_type, "PAPER")

    def test_get_queryset_filters_by_date(self):
        """Test date filtering."""
        # Create old document
        old_date = timezone.now() - timedelta(days=100)
        old_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )
        old_doc.created_date = old_date
        old_doc.save()

        # Create recent document
        recent_date = timezone.now() - timedelta(days=1)
        recent_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )
        recent_doc.created_date = recent_date
        recent_doc.save()

        # Filter by start date
        start_date = timezone.now() - timedelta(days=50)
        queryset = self.mapper.get_queryset(start_date=start_date)

        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, recent_doc.id)

    def test_map_to_item_row_paper(self):
        """Test mapping a paper document to a row."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", score=10
        )
        unified_doc.hubs.add(self.hub)

        Paper.objects.create(
            title="Test Paper",
            paper_title="Official Test Paper",
            abstract="This is a test abstract.",
            uploaded_by=self.user,
            unified_document=unified_doc,
            citations=5,
        )

        row = self.mapper.map_to_item_row(unified_doc)

        # Check common fields
        self.assertEqual(row["ITEM_ID"], str(unified_doc.id))
        self.assertEqual(row["ITEM_TYPE"], "PAPER")
        self.assertEqual(row["SCORE"], 10)
        self.assertIsNotNone(row["CREATION_TIMESTAMP"])

        # Check paper-specific fields
        self.assertIsNotNone(row["TEXT"])  # Should have cleaned abstract
        self.assertIsNotNone(row["TITLE"])  # Should have concatenated title
        self.assertEqual(row["CITATION_COUNT_TOTAL"], 5)

    def test_map_to_item_row_post(self):
        """Test mapping a post document to a row."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION", score=15
        )
        unified_doc.hubs.add(self.hub)

        ResearchhubPost.objects.create(
            title="Test Post",
            renderable_text="This is a test post content.",
            created_by=self.user,
            unified_document=unified_doc,
            document_type="DISCUSSION",
        )

        row = self.mapper.map_to_item_row(unified_doc)

        # Check common fields
        self.assertEqual(row["ITEM_ID"], str(unified_doc.id))
        self.assertEqual(row["ITEM_TYPE"], "DISCUSSION")
        self.assertEqual(row["SCORE"], 15)

        # Check post-specific fields
        self.assertIsNotNone(row["TEXT"])  # Should have cleaned renderable_text
        self.assertIsNotNone(row["TITLE"])  # Should have concatenated title

        # Posts don't have citation counts
        self.assertIsNone(row["CITATION_COUNT_TOTAL"])

    def test_map_to_item_row_with_special_chars(self):
        """Test mapping document with special characters in text."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        Paper.objects.create(
            title='Test, Paper: With "Quotes"',
            abstract="Abstract with\nnewlines\tand\ttabs",
            uploaded_by=self.user,
            unified_document=unified_doc,
        )

        row = self.mapper.map_to_item_row(unified_doc)

        # Check that TEXT is cleaned
        self.assertIsNotNone(row["TEXT"])
        self.assertNotIn("\n", row["TEXT"])
        self.assertNotIn("\t", row["TEXT"])

    def test_map_to_item_row_paper_with_external_metadata(self):
        """Test mapping a paper with external metadata (Altmetric data)."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
            unified_document=unified_doc,
            external_metadata={"bluesky_count": 10, "twitter_count": 25},
        )

        row = self.mapper.map_to_item_row(unified_doc)

        # Check social metrics
        self.assertEqual(row["BLUESKY_COUNT_TOTAL"], 10)
        self.assertEqual(row["TWEET_COUNT_TOTAL"], 25)

    def test_map_to_item_row_grant(self):
        """Test mapping a grant (RFP) document."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="GRANT")
        unified_doc.hubs.add(self.hub)

        ResearchhubPost.objects.create(
            title="Test Grant",
            document_type="GRANT",
            created_by=self.user,
            unified_document=unified_doc,
        )

        row = self.mapper.map_to_item_row(unified_doc)

        self.assertEqual(row["ITEM_TYPE"], "GRANT")
        # RFP-specific fields should be present (even if None)
        self.assertIn("REQUEST_FOR_PROPOSAL_AMOUNT", row)
        self.assertIn("REQUEST_FOR_PROPOSAL_EXPIRES_AT", row)
        self.assertIn("REQUEST_FOR_PROPOSAL_NUM_OF_APPLICANTS", row)

    def test_map_to_item_row_preregistration(self):
        """Test mapping a preregistration (proposal) document."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION"
        )
        unified_doc.hubs.add(self.hub)

        ResearchhubPost.objects.create(
            title="Test Proposal",
            document_type="PREREGISTRATION",
            created_by=self.user,
            unified_document=unified_doc,
        )

        row = self.mapper.map_to_item_row(unified_doc)

        self.assertEqual(row["ITEM_TYPE"], "PREREGISTRATION")
        # Proposal-specific fields should be present (even if None)
        self.assertIn("PROPOSAL_AMOUNT", row)
        self.assertIn("PROPOSAL_EXPIRES_AT", row)
        self.assertIn("PROPOSAL_NUM_OF_FUNDERS", row)
