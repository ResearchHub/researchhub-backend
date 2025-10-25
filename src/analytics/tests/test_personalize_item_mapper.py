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
        # Create a document with paper, then soft-delete it
        removed_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        Paper.objects.create(
            title="Removed Paper",
            uploaded_by=self.user,
            unified_document=removed_doc,
            retrieved_from_external_source=False,
        )
        # Perform soft deletion
        removed_doc.is_removed = True
        removed_doc.save()

        # Create non-removed document with paper
        active_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        Paper.objects.create(
            title="Active Paper",
            uploaded_by=self.user,
            unified_document=active_doc,
            retrieved_from_external_source=False,
        )

        queryset = self.mapper.get_queryset()

        # Only active document should be returned
        self.assertEqual(queryset.count(), 1)
        returned_ids = list(queryset.values_list("id", flat=True))
        self.assertIn(active_doc.id, returned_ids)
        self.assertNotIn(removed_doc.id, returned_ids)

    def test_get_queryset_excludes_note_type(self):
        """Test that NOTE document type is excluded."""
        # Create NOTE document
        ResearchhubUnifiedDocument.objects.create(
            document_type="NOTE", is_removed=False
        )

        # Create PAPER document
        paper_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )
        Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
            unified_document=paper_doc,
            retrieved_from_external_source=False,
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
        Paper.objects.create(
            title="Old Paper",
            uploaded_by=self.user,
            unified_document=old_doc,
            retrieved_from_external_source=False,
        )

        # Create recent document
        recent_date = timezone.now() - timedelta(days=1)
        recent_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )
        recent_doc.created_date = recent_date
        recent_doc.save()
        Paper.objects.create(
            title="Recent Paper",
            uploaded_by=self.user,
            unified_document=recent_doc,
            retrieved_from_external_source=False,
        )

        # Filter by start date
        start_date = timezone.now() - timedelta(days=50)
        queryset = self.mapper.get_queryset(start_date=start_date)

        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, recent_doc.id)

    def test_get_queryset_includes_native_papers(self):
        """Test that native (user-submitted) papers are always included."""
        native_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )
        Paper.objects.create(
            title="Native Paper",
            uploaded_by=self.user,
            unified_document=native_doc,
            retrieved_from_external_source=False,
        )

        queryset = self.mapper.get_queryset()
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, native_doc.id)

    def test_get_queryset_excludes_external_papers_without_item_ids(self):
        """Test that external papers are excluded when no item_ids provided."""
        # Create external paper
        external_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )
        Paper.objects.create(
            title="External Paper",
            uploaded_by=self.user,
            unified_document=external_doc,
            retrieved_from_external_source=True,
        )

        queryset = self.mapper.get_queryset()
        self.assertEqual(queryset.count(), 0)

    def test_get_queryset_includes_external_papers_when_in_item_ids(self):
        """Test that external papers are included when their ID is in item_ids."""
        # Create external paper
        external_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )
        Paper.objects.create(
            title="External Paper",
            uploaded_by=self.user,
            unified_document=external_doc,
            retrieved_from_external_source=True,
        )

        # Query with item_ids (simulating interaction export)
        queryset = self.mapper.get_queryset(item_ids={external_doc.id})
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, external_doc.id)

    def test_get_queryset_with_item_ids_filters_correctly(self):
        """Test that item_ids filter works for mixed content types."""
        # Create native paper
        native_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )
        Paper.objects.create(
            title="Native Paper",
            uploaded_by=self.user,
            unified_document=native_doc,
            retrieved_from_external_source=False,
        )

        # Create external paper
        external_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )
        Paper.objects.create(
            title="External Paper",
            uploaded_by=self.user,
            unified_document=external_doc,
            retrieved_from_external_source=True,
        )

        # Create post
        post_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION", is_removed=False
        )
        ResearchhubPost.objects.create(
            title="Test Post",
            document_type="DISCUSSION",
            created_by=self.user,
            unified_document=post_doc,
        )

        # Query with specific item_ids
        queryset = self.mapper.get_queryset(item_ids={native_doc.id, post_doc.id})
        self.assertEqual(queryset.count(), 2)
        ids = set(queryset.values_list("id", flat=True))
        self.assertEqual(ids, {native_doc.id, post_doc.id})

    def test_get_queryset_includes_all_posts(self):
        """Test that all post types are included regardless of interactions."""
        # Create GRANT post
        grant_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="GRANT", is_removed=False
        )
        ResearchhubPost.objects.create(
            title="Test Grant",
            document_type="GRANT",
            created_by=self.user,
            unified_document=grant_doc,
        )

        # Create DISCUSSION post
        discussion_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION", is_removed=False
        )
        ResearchhubPost.objects.create(
            title="Test Discussion",
            document_type="DISCUSSION",
            created_by=self.user,
            unified_document=discussion_doc,
        )

        queryset = self.mapper.get_queryset()
        self.assertEqual(queryset.count(), 2)

    def test_map_to_item_row_paper(self):
        """Test mapping a paper document to a row."""
        from analytics.services.personalize_item_utils import datetime_to_epoch_seconds

        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", score=10
        )
        unified_doc.hubs.add(self.hub)

        paper_publish_date = timezone.now() - timedelta(days=30)
        paper = Paper.objects.create(
            title="Test Paper",
            paper_title="Official Test Paper",
            abstract="This is a test abstract.",
            uploaded_by=self.user,
            unified_document=unified_doc,
            citations=5,
            paper_publish_date=paper_publish_date,
        )

        row = self.mapper.map_to_item_row(unified_doc)

        # Check common fields
        self.assertEqual(row["ITEM_ID"], str(unified_doc.id))
        self.assertEqual(row["ITEM_TYPE"], "PAPER")
        self.assertEqual(row["SCORE"], 10)
        self.assertIsNotNone(row["CREATION_TIMESTAMP"])
        # For papers, should use paper_publish_date instead of created_date
        self.assertEqual(
            row["CREATION_TIMESTAMP"],
            datetime_to_epoch_seconds(paper.paper_publish_date),
        )

        # Check paper-specific fields
        self.assertIsNotNone(row["TEXT"])  # Should have cleaned abstract
        self.assertIsNotNone(row["TITLE"])  # Should have concatenated title
        self.assertEqual(row["CITATION_COUNT_TOTAL"], 5)

    def test_map_to_item_row_post(self):
        """Test mapping a post document to a row."""
        from analytics.services.personalize_item_utils import datetime_to_epoch_seconds

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
        # For posts, should use unified_doc.created_date
        self.assertEqual(
            row["CREATION_TIMESTAMP"],
            datetime_to_epoch_seconds(unified_doc.created_date),
        )

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
            external_metadata={
                "metrics": {
                    "bluesky_count": 10,
                    "twitter_count": 25,
                    "score": 1.25,
                    "altmetric_id": 182730539,
                }
            },
        )

        row = self.mapper.map_to_item_row(unified_doc)

        # Check social metrics (now nested in "metrics" object)
        self.assertEqual(row["BLUESKY_COUNT_TOTAL"], 10)
        self.assertEqual(row["TWEET_COUNT_TOTAL"], 25)

    def test_map_to_item_row_paper_without_metrics_object(self):
        """Test mapping a paper with external_metadata but no metrics object."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
            unified_document=unified_doc,
            external_metadata={"other_data": "value"},  # No "metrics" object
        )

        row = self.mapper.map_to_item_row(unified_doc)

        # Should default to 0 when metrics object is missing
        self.assertEqual(row["BLUESKY_COUNT_TOTAL"], 0)
        self.assertEqual(row["TWEET_COUNT_TOTAL"], 0)

    def test_map_to_item_row_paper_without_publish_date(self):
        """Test that papers without paper_publish_date fall back to created_date."""
        from analytics.services.personalize_item_utils import datetime_to_epoch_seconds

        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", score=10
        )

        Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
            unified_document=unified_doc,
            paper_publish_date=None,  # Explicitly None
        )

        row = self.mapper.map_to_item_row(unified_doc)

        # Should fall back to unified_doc.created_date
        self.assertEqual(
            row["CREATION_TIMESTAMP"],
            datetime_to_epoch_seconds(unified_doc.created_date),
        )

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

    def test_get_queryset_with_since_date_includes_all_recent_papers(self):
        """Test that all papers >= since_date are included (external and native)."""
        from datetime import datetime

        recent_date = datetime(2024, 1, 1)
        old_date = datetime(2023, 1, 1)

        # Create old external paper (should be excluded)
        old_external_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        old_paper = Paper.objects.create(
            title="Old External Paper",
            uploaded_by=self.user,
            unified_document=old_external_doc,
            retrieved_from_external_source=True,
        )
        # Update created_date after creation
        # (auto_now_add prevents setting it during create)
        Paper.objects.filter(id=old_paper.id).update(created_date=old_date)

        # Create recent external paper (should be included)
        recent_external_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        recent_paper = Paper.objects.create(
            title="Recent External Paper",
            uploaded_by=self.user,
            unified_document=recent_external_doc,
            retrieved_from_external_source=True,
        )
        Paper.objects.filter(id=recent_paper.id).update(created_date=recent_date)

        # Create old native paper (should be included - always include native)
        old_native_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        old_native_paper = Paper.objects.create(
            title="Old Native Paper",
            uploaded_by=self.user,
            unified_document=old_native_doc,
            retrieved_from_external_source=False,
        )
        Paper.objects.filter(id=old_native_paper.id).update(created_date=old_date)

        queryset = self.mapper.get_queryset(since_date=recent_date)
        returned_ids = list(queryset.values_list("id", flat=True))

        # Recent external paper should be included
        self.assertIn(recent_external_doc.id, returned_ids)
        # Old native paper should be included (always include native)
        self.assertIn(old_native_doc.id, returned_ids)
        # Old external paper should NOT be included
        self.assertNotIn(old_external_doc.id, returned_ids)

    def test_get_queryset_with_since_date_and_item_ids(self):
        """Test that papers since date OR in item_ids are included."""
        from datetime import datetime

        recent_date = datetime(2024, 1, 1)
        old_date = datetime(2023, 1, 1)

        # Create old external paper with interaction (should be included)
        old_with_interaction_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        old_with_int_paper = Paper.objects.create(
            title="Old Paper With Interaction",
            uploaded_by=self.user,
            unified_document=old_with_interaction_doc,
            retrieved_from_external_source=True,
        )
        Paper.objects.filter(id=old_with_int_paper.id).update(created_date=old_date)

        # Create old external paper without interaction (should be excluded)
        old_no_interaction_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        old_no_int_paper = Paper.objects.create(
            title="Old Paper No Interaction",
            uploaded_by=self.user,
            unified_document=old_no_interaction_doc,
            retrieved_from_external_source=True,
        )
        Paper.objects.filter(id=old_no_int_paper.id).update(created_date=old_date)

        # Create recent external paper (should be included)
        recent_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        recent_paper_2 = Paper.objects.create(
            title="Recent External Paper",
            uploaded_by=self.user,
            unified_document=recent_doc,
            retrieved_from_external_source=True,
        )
        Paper.objects.filter(id=recent_paper_2.id).update(created_date=recent_date)

        # Query with since_date and item_ids
        item_ids = {old_with_interaction_doc.id}
        queryset = self.mapper.get_queryset(since_date=recent_date, item_ids=item_ids)
        returned_ids = list(queryset.values_list("id", flat=True))

        # Recent paper should be included (since date)
        self.assertIn(recent_doc.id, returned_ids)
        # Old paper with interaction should be included (in item_ids)
        self.assertIn(old_with_interaction_doc.id, returned_ids)
        # Old paper without interaction should NOT be included
        self.assertNotIn(old_no_interaction_doc.id, returned_ids)

    def test_get_queryset_with_since_date_excludes_old_external_papers(self):
        """Test that old external papers without interactions are excluded."""
        from datetime import datetime

        recent_date = datetime(2024, 1, 1)
        old_date = datetime(2023, 1, 1)

        # Create old external paper
        old_external_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        old_ext_paper = Paper.objects.create(
            title="Old External Paper",
            uploaded_by=self.user,
            unified_document=old_external_doc,
            retrieved_from_external_source=True,
        )
        Paper.objects.filter(id=old_ext_paper.id).update(created_date=old_date)

        # Create a post (should always be included)
        post_doc = ResearchhubUnifiedDocument.objects.create(document_type="DISCUSSION")
        ResearchhubPost.objects.create(
            title="Test Post",
            document_type="DISCUSSION",
            created_by=self.user,
            unified_document=post_doc,
        )

        queryset = self.mapper.get_queryset(since_date=recent_date)
        returned_ids = list(queryset.values_list("id", flat=True))

        # Old external paper should NOT be included
        self.assertNotIn(old_external_doc.id, returned_ids)
        # Post should be included (posts always included)
        self.assertIn(post_doc.id, returned_ids)
