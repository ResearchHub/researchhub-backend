"""
Unit tests for Peer Review mapper.

Tests the mapping of Review records to Personalize interactions.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone as django_timezone

from analytics.services.personalize_constants import EVENT_WEIGHTS, PEER_REVIEW_CREATED
from analytics.services.personalize_mappers.peer_review_mapper import PeerReviewMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from review.models.review_model import Review
from user.models import User


class TestPeerReviewMapper(TestCase):
    """Tests for PeerReviewMapper class."""

    def setUp(self):
        self.user = User.objects.create(username="testuser", email="test@example.com")
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )

    def test_event_type_name(self):
        """Test event type name property."""
        mapper = PeerReviewMapper()
        self.assertEqual(mapper.event_type_name, "peer_review")

    def test_get_queryset_returns_all_reviews(self):
        """Test that queryset includes all reviews."""
        # Create multiple reviews
        review1 = Review.objects.create(
            created_by=self.user,
            unified_document=self.unified_doc,
            score=8.0,
        )

        unified_doc2 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        review2 = Review.objects.create(
            created_by=self.user,
            unified_document=unified_doc2,
            score=7.5,
        )

        mapper = PeerReviewMapper()
        queryset = mapper.get_queryset()

        # Should return all reviews
        self.assertEqual(queryset.count(), 2)
        review_ids = list(queryset.values_list("id", flat=True))
        self.assertIn(review1.id, review_ids)
        self.assertIn(review2.id, review_ids)

    def test_get_queryset_with_date_filters(self):
        """Test queryset filtering by date range."""
        now = django_timezone.now()
        past_date = now - timedelta(days=10)

        # Create review in the past
        past_review = Review.objects.create(
            created_by=self.user,
            unified_document=self.unified_doc,
            score=8.0,
        )
        past_review.created_date = past_date
        past_review.save()

        # Create review now
        unified_doc2 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        current_review = Review.objects.create(
            created_by=self.user,
            unified_document=unified_doc2,
            score=7.5,
        )

        mapper = PeerReviewMapper()

        # Filter by start date
        queryset = mapper.get_queryset(start_date=now - timedelta(days=1))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, current_review.id)

        # Filter by end date
        queryset = mapper.get_queryset(end_date=now - timedelta(days=5))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, past_review.id)

        # Filter by date range
        queryset = mapper.get_queryset(
            start_date=past_date - timedelta(days=1),
            end_date=now + timedelta(days=1),
        )
        self.assertEqual(queryset.count(), 2)

    def test_map_review_to_interaction(self):
        """Test mapping a review to PEER_REVIEW_CREATED interaction."""
        review = Review.objects.create(
            created_by=self.user,
            unified_document=self.unified_doc,
            score=8.5,
        )

        mapper = PeerReviewMapper()
        interactions = mapper.map_to_interactions(review)

        # Should create exactly one interaction
        self.assertEqual(len(interactions), 1)

        interaction = interactions[0]
        self.assertEqual(interaction["USER_ID"], str(self.user.id))
        self.assertEqual(interaction["ITEM_ID"], str(self.unified_doc.id))
        self.assertEqual(interaction["EVENT_TYPE"], PEER_REVIEW_CREATED)
        self.assertEqual(interaction["EVENT_VALUE"], EVENT_WEIGHTS[PEER_REVIEW_CREATED])
        self.assertIsNone(interaction["DEVICE"])
        self.assertIsNone(interaction["IMPRESSION"])
        self.assertIsNone(interaction["RECOMMENDATION_ID"])
        self.assertEqual(
            interaction["TIMESTAMP"],
            datetime_to_epoch_seconds(review.created_date),
        )

    def test_map_review_without_unified_doc(self):
        """Test that reviews without unified document are skipped."""
        review = Review.objects.create(
            created_by=self.user,
            unified_document=None,
            score=8.0,
        )

        mapper = PeerReviewMapper()
        interactions = mapper.map_to_interactions(review)

        # Should return empty list
        self.assertEqual(len(interactions), 0)

    def test_map_review_without_creator(self):
        """Test that reviews without creator are skipped."""
        review = Review.objects.create(
            created_by=None,
            unified_document=self.unified_doc,
            score=8.0,
        )

        mapper = PeerReviewMapper()
        interactions = mapper.map_to_interactions(review)

        # Should return empty list
        self.assertEqual(len(interactions), 0)

    def test_timestamp_is_integer(self):
        """Test that timestamp is converted to integer epoch seconds."""
        review = Review.objects.create(
            created_by=self.user,
            unified_document=self.unified_doc,
            score=8.0,
        )

        mapper = PeerReviewMapper()
        interactions = mapper.map_to_interactions(review)

        timestamp = interactions[0]["TIMESTAMP"]
        self.assertIsInstance(timestamp, int)
        # Timestamp should be reasonable (after 2020)
        self.assertGreater(timestamp, 1577836800)  # Jan 1, 2020
