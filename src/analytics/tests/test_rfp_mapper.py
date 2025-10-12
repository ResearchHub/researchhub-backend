"""
Unit tests for RFP (Grant) mapper.

Tests the mapping of Grant ResearchhubPost to Personalize interactions.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone as django_timezone

from analytics.services.personalize_constants import EVENT_WEIGHTS, RFP_CREATED
from analytics.services.personalize_mappers.rfp_mapper import RfpMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class TestRfpMapper(TestCase):
    """Tests for RfpMapper class."""

    def setUp(self):
        self.user = User.objects.create(username="testuser", email="test@example.com")
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT
        )

    def test_event_type_name(self):
        """Test event type name property."""
        mapper = RfpMapper()
        self.assertEqual(mapper.event_type_name, "rfp")

    def test_get_queryset_filters_by_grant_type(self):
        """Test that queryset only includes GRANT type posts."""
        # Create GRANT post
        grant_post = ResearchhubPost.objects.create(
            title="Test Grant",
            document_type=GRANT,
            unified_document=self.unified_doc,
            created_by=self.user,
        )

        # Create DISCUSSION post (should be excluded)
        discussion_unified = ResearchhubUnifiedDocument.objects.create(
            document_type=DISCUSSION
        )
        ResearchhubPost.objects.create(
            title="Test Discussion",
            document_type=DISCUSSION,
            unified_document=discussion_unified,
            created_by=self.user,
        )

        mapper = RfpMapper()
        queryset = mapper.get_queryset()

        # Should only return grant post
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, grant_post.id)
        self.assertEqual(queryset.first().document_type, GRANT)

    def test_get_queryset_with_date_filters(self):
        """Test queryset filtering by date range."""
        now = django_timezone.now()
        past_date = now - timedelta(days=10)

        # Create grant in the past
        past_grant = ResearchhubPost.objects.create(
            title="Past Grant",
            document_type=GRANT,
            unified_document=self.unified_doc,
            created_by=self.user,
        )
        past_grant.created_date = past_date
        past_grant.save()

        # Create grant now
        unified_doc2 = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        current_grant = ResearchhubPost.objects.create(
            title="Current Grant",
            document_type=GRANT,
            unified_document=unified_doc2,
            created_by=self.user,
        )

        mapper = RfpMapper()

        # Filter by start date
        queryset = mapper.get_queryset(start_date=now - timedelta(days=1))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, current_grant.id)

        # Filter by end date
        queryset = mapper.get_queryset(end_date=now - timedelta(days=5))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, past_grant.id)

        # Filter by date range
        queryset = mapper.get_queryset(
            start_date=past_date - timedelta(days=1),
            end_date=now + timedelta(days=1),
        )
        self.assertEqual(queryset.count(), 2)

    def test_map_rfp_to_interaction(self):
        """Test mapping a grant post to RFP_CREATED interaction."""
        grant_post = ResearchhubPost.objects.create(
            title="Test Grant",
            document_type=GRANT,
            unified_document=self.unified_doc,
            created_by=self.user,
        )

        mapper = RfpMapper()
        interactions = mapper.map_to_interactions(grant_post)

        # Should create exactly one interaction
        self.assertEqual(len(interactions), 1)

        interaction = interactions[0]
        self.assertEqual(interaction["USER_ID"], str(self.user.id))
        self.assertEqual(interaction["ITEM_ID"], str(self.unified_doc.id))
        self.assertEqual(interaction["EVENT_TYPE"], RFP_CREATED)
        self.assertEqual(interaction["EVENT_VALUE"], EVENT_WEIGHTS[RFP_CREATED])
        self.assertIsNone(interaction["DEVICE"])
        self.assertIsNone(interaction["IMPRESSION"])
        self.assertIsNone(interaction["RECOMMENDATION_ID"])
        self.assertEqual(
            interaction["TIMESTAMP"],
            datetime_to_epoch_seconds(grant_post.created_date),
        )

    def test_map_rfp_without_unified_doc(self):
        """Test that posts without unified document are skipped."""
        grant_post = ResearchhubPost.objects.create(
            title="Test Grant No Doc",
            document_type=GRANT,
            unified_document=None,
            created_by=self.user,
        )

        mapper = RfpMapper()
        interactions = mapper.map_to_interactions(grant_post)

        # Should return empty list
        self.assertEqual(len(interactions), 0)

    def test_map_rfp_without_creator(self):
        """Test that posts without creator are skipped."""
        grant_post = ResearchhubPost.objects.create(
            title="Test Grant No Creator",
            document_type=GRANT,
            unified_document=self.unified_doc,
            created_by=None,
        )

        mapper = RfpMapper()
        interactions = mapper.map_to_interactions(grant_post)

        # Should return empty list
        self.assertEqual(len(interactions), 0)

    def test_timestamp_is_integer(self):
        """Test that timestamp is converted to integer epoch seconds."""
        grant_post = ResearchhubPost.objects.create(
            title="Test Grant",
            document_type=GRANT,
            unified_document=self.unified_doc,
            created_by=self.user,
        )

        mapper = RfpMapper()
        interactions = mapper.map_to_interactions(grant_post)

        timestamp = interactions[0]["TIMESTAMP"]
        self.assertIsInstance(timestamp, int)
        # Timestamp should be reasonable (after 2020)
        self.assertGreater(timestamp, 1577836800)  # Jan 1, 2020
