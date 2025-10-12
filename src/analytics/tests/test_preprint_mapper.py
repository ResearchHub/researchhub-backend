"""
Unit tests for Preprint mapper.

Tests the mapping of user-submitted Paper records (preprints) to Personalize
interactions, including critical tests for excluding external source papers.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone as django_timezone

from analytics.services.personalize_constants import EVENT_WEIGHTS, PREPRINT_SUBMITTED
from analytics.services.personalize_mappers.preprint_mapper import PreprintMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from paper.models import Paper
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class TestPreprintMapper(TestCase):
    """Tests for PreprintMapper class."""

    def setUp(self):
        self.user = User.objects.create(username="testuser", email="test@example.com")

    def test_event_type_name(self):
        """Test event type name property."""
        mapper = PreprintMapper()
        self.assertEqual(mapper.event_type_name, "preprint")

    def test_get_queryset_only_user_submitted(self):
        """Test that only user-submitted papers are included."""
        unified_doc1 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        unified_doc2 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        # User-submitted preprint (should be included)
        user_paper = Paper.objects.create(
            title="User Preprint",
            unified_document=unified_doc1,
            uploaded_by=self.user,
            retrieved_from_external_source=False,
            work_type="preprint",
        )

        # External source paper (should be excluded)
        Paper.objects.create(
            title="External Paper",
            unified_document=unified_doc2,
            uploaded_by=self.user,
            retrieved_from_external_source=True,  # External source
            work_type="preprint",
            external_source="arXiv",
        )

        mapper = PreprintMapper()
        queryset = mapper.get_queryset()

        # Should only return user-submitted paper
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, user_paper.id)
        self.assertFalse(queryset.first().retrieved_from_external_source)

    def test_get_queryset_only_preprints(self):
        """Test that only work_type='preprint' papers are included."""
        unified_doc1 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        unified_doc2 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        # Preprint (should be included)
        preprint = Paper.objects.create(
            title="Preprint",
            unified_document=unified_doc1,
            uploaded_by=self.user,
            retrieved_from_external_source=False,
            work_type="preprint",
        )

        # Article (should be excluded)
        Paper.objects.create(
            title="Article",
            unified_document=unified_doc2,
            uploaded_by=self.user,
            retrieved_from_external_source=False,
            work_type="article",
        )

        mapper = PreprintMapper()
        queryset = mapper.get_queryset()

        # Should only return preprint
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, preprint.id)
        self.assertEqual(queryset.first().work_type, "preprint")

    def test_excludes_papers_without_uploader(self):
        """Test that papers without uploaded_by are excluded."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        # Paper with uploader (should be included)
        user_paper = Paper.objects.create(
            title="User Paper",
            unified_document=unified_doc,
            uploaded_by=self.user,
            retrieved_from_external_source=False,
            work_type="preprint",
        )

        # Paper without uploader (should be excluded)
        unified_doc2 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        Paper.objects.create(
            title="No Uploader Paper",
            unified_document=unified_doc2,
            uploaded_by=None,  # No uploader
            retrieved_from_external_source=False,
            work_type="preprint",
        )

        mapper = PreprintMapper()
        queryset = mapper.get_queryset()

        # Should only return paper with uploader
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, user_paper.id)

    def test_get_queryset_with_date_filters(self):
        """Test queryset filtering by date range."""
        now = django_timezone.now()
        past_date = now - timedelta(days=10)

        unified_doc1 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        unified_doc2 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        # Create paper in the past
        past_paper = Paper.objects.create(
            title="Past Preprint",
            unified_document=unified_doc1,
            uploaded_by=self.user,
            retrieved_from_external_source=False,
            work_type="preprint",
        )
        past_paper.created_date = past_date
        past_paper.save()

        # Create paper now
        current_paper = Paper.objects.create(
            title="Current Preprint",
            unified_document=unified_doc2,
            uploaded_by=self.user,
            retrieved_from_external_source=False,
            work_type="preprint",
        )

        mapper = PreprintMapper()

        # Filter by start date
        queryset = mapper.get_queryset(start_date=now - timedelta(days=1))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, current_paper.id)

        # Filter by end date
        queryset = mapper.get_queryset(end_date=now - timedelta(days=5))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, past_paper.id)

        # Filter by date range
        queryset = mapper.get_queryset(
            start_date=past_date - timedelta(days=1),
            end_date=now + timedelta(days=1),
        )
        self.assertEqual(queryset.count(), 2)

    def test_map_preprint_submission(self):
        """Test mapping a preprint submission to PREPRINT_SUBMITTED."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        paper = Paper.objects.create(
            title="Test Preprint",
            unified_document=unified_doc,
            uploaded_by=self.user,
            retrieved_from_external_source=False,
            work_type="preprint",
        )

        mapper = PreprintMapper()
        interactions = mapper.map_to_interactions(paper)

        # Should create exactly one interaction
        self.assertEqual(len(interactions), 1)

        interaction = interactions[0]
        self.assertEqual(interaction["USER_ID"], str(self.user.id))
        self.assertEqual(interaction["ITEM_ID"], str(unified_doc.id))
        self.assertEqual(interaction["EVENT_TYPE"], PREPRINT_SUBMITTED)
        self.assertEqual(interaction["EVENT_VALUE"], EVENT_WEIGHTS[PREPRINT_SUBMITTED])
        self.assertEqual(interaction["EVENT_VALUE"], 2.0)
        self.assertIsNone(interaction["DEVICE"])
        self.assertIsNone(interaction["IMPRESSION"])
        self.assertIsNone(interaction["RECOMMENDATION_ID"])
        self.assertEqual(
            interaction["TIMESTAMP"],
            datetime_to_epoch_seconds(paper.created_date),
        )

    def test_map_paper_without_uploader(self):
        """Test that papers without uploader are skipped."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        paper = Paper.objects.create(
            title="No Uploader Paper",
            unified_document=unified_doc,
            uploaded_by=None,  # No uploader
            retrieved_from_external_source=False,
            work_type="preprint",
        )

        mapper = PreprintMapper()
        interactions = mapper.map_to_interactions(paper)

        # Should return empty list
        self.assertEqual(len(interactions), 0)

    def test_map_paper_without_unified_document(self):
        """Test that papers without unified_document are skipped."""
        paper = Paper.objects.create(
            title="No Unified Doc Paper",
            unified_document=None,  # No unified document
            uploaded_by=self.user,
            retrieved_from_external_source=False,
            work_type="preprint",
        )

        mapper = PreprintMapper()
        interactions = mapper.map_to_interactions(paper)

        # Should return empty list
        self.assertEqual(len(interactions), 0)

    def test_excludes_external_papers(self):
        """Test that papers from external sources are excluded."""
        unified_doc1 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        unified_doc2 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        unified_doc3 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        # User-submitted preprint (should be included)
        user_paper = Paper.objects.create(
            title="User Preprint",
            unified_document=unified_doc1,
            uploaded_by=self.user,
            retrieved_from_external_source=False,
            work_type="preprint",
        )

        # bioRxiv paper (should be excluded)
        Paper.objects.create(
            title="bioRxiv Paper",
            unified_document=unified_doc2,
            uploaded_by=self.user,
            retrieved_from_external_source=True,
            work_type="preprint",
            external_source="bioRxiv",
        )

        # arXiv paper (should be excluded)
        Paper.objects.create(
            title="arXiv Paper",
            unified_document=unified_doc3,
            uploaded_by=self.user,
            retrieved_from_external_source=True,
            work_type="preprint",
            external_source="arXiv",
        )

        mapper = PreprintMapper()
        queryset = mapper.get_queryset()

        # Should only return user-submitted paper
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, user_paper.id)

    def test_timestamp_is_integer(self):
        """Test that timestamp is converted to integer epoch seconds."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        paper = Paper.objects.create(
            title="Test Preprint",
            unified_document=unified_doc,
            uploaded_by=self.user,
            retrieved_from_external_source=False,
            work_type="preprint",
        )

        mapper = PreprintMapper()
        interactions = mapper.map_to_interactions(paper)

        timestamp = interactions[0]["TIMESTAMP"]
        self.assertIsInstance(timestamp, int)
        # Timestamp should be reasonable (after 2020)
        self.assertGreater(timestamp, 1577836800)  # Jan 1, 2020
