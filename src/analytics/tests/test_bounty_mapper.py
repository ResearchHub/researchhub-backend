"""
Unit tests for Bounty creation mapper.

Tests the mapping of Bounty records to Personalize interactions.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone as django_timezone

from analytics.services.personalize_constants import BOUNTY_CREATED, EVENT_WEIGHTS
from analytics.services.personalize_mappers.bounty_mapper import BountyMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from reputation.related_models.bounty import Bounty
from reputation.related_models.escrow import Escrow
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class TestBountyMapper(TestCase):
    """Tests for BountyMapper class."""

    def setUp(self):
        self.user = User.objects.create(username="testuser", email="test@example.com")
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION"
        )
        self.escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
        )

    def test_event_type_name(self):
        """Test event type name property."""
        mapper = BountyMapper()
        self.assertEqual(mapper.event_type_name, "bounty")

    def test_get_queryset_returns_all_bounties(self):
        """Test that queryset includes all bounties."""
        # Create multiple bounties
        bounty1 = Bounty.objects.create(
            created_by=self.user,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=100,
        )

        unified_doc2 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        escrow2 = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
        )
        bounty2 = Bounty.objects.create(
            created_by=self.user,
            escrow=escrow2,
            unified_document=unified_doc2,
            amount=200,
        )

        mapper = BountyMapper()
        queryset = mapper.get_queryset()

        # Should return all bounties
        self.assertEqual(queryset.count(), 2)
        bounty_ids = list(queryset.values_list("id", flat=True))
        self.assertIn(bounty1.id, bounty_ids)
        self.assertIn(bounty2.id, bounty_ids)

    def test_get_queryset_with_date_filters(self):
        """Test queryset filtering by date range."""
        now = django_timezone.now()
        past_date = now - timedelta(days=10)

        # Create bounty in the past
        past_bounty = Bounty.objects.create(
            created_by=self.user,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=100,
        )
        past_bounty.created_date = past_date
        past_bounty.save()

        # Create bounty now
        unified_doc2 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        escrow2 = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
        )
        current_bounty = Bounty.objects.create(
            created_by=self.user,
            escrow=escrow2,
            unified_document=unified_doc2,
            amount=200,
        )

        mapper = BountyMapper()

        # Filter by start date
        queryset = mapper.get_queryset(start_date=now - timedelta(days=1))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, current_bounty.id)

        # Filter by end date
        queryset = mapper.get_queryset(end_date=now - timedelta(days=5))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, past_bounty.id)

        # Filter by date range
        queryset = mapper.get_queryset(
            start_date=past_date - timedelta(days=1),
            end_date=now + timedelta(days=1),
        )
        self.assertEqual(queryset.count(), 2)

    def test_map_bounty_to_interaction(self):
        """Test mapping a bounty to BOUNTY_CREATED interaction."""
        bounty = Bounty.objects.create(
            created_by=self.user,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=100,
        )

        mapper = BountyMapper()
        interactions = mapper.map_to_interactions(bounty)

        # Should create exactly one interaction
        self.assertEqual(len(interactions), 1)

        interaction = interactions[0]
        self.assertEqual(interaction["USER_ID"], str(self.user.id))
        self.assertEqual(interaction["ITEM_ID"], str(self.unified_doc.id))
        self.assertEqual(interaction["EVENT_TYPE"], BOUNTY_CREATED)
        self.assertEqual(interaction["EVENT_VALUE"], EVENT_WEIGHTS[BOUNTY_CREATED])
        self.assertIsNone(interaction["DEVICE"])
        self.assertIsNone(interaction["IMPRESSION"])
        self.assertIsNone(interaction["RECOMMENDATION_ID"])
        self.assertEqual(
            interaction["TIMESTAMP"],
            datetime_to_epoch_seconds(bounty.created_date),
        )

    def test_map_bounty_without_unified_doc(self):
        """Test that bounties without unified document are skipped."""
        bounty = Bounty.objects.create(
            created_by=self.user,
            escrow=self.escrow,
            unified_document=None,
            amount=100,
        )

        mapper = BountyMapper()
        interactions = mapper.map_to_interactions(bounty)

        # Should return empty list
        self.assertEqual(len(interactions), 0)

    def test_map_bounty_without_creator(self):
        """Test that bounties without creator are skipped."""
        bounty = Bounty.objects.create(
            created_by=None,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=100,
        )

        mapper = BountyMapper()
        interactions = mapper.map_to_interactions(bounty)

        # Should return empty list
        self.assertEqual(len(interactions), 0)

    def test_timestamp_is_integer(self):
        """Test that timestamp is converted to integer epoch seconds."""
        bounty = Bounty.objects.create(
            created_by=self.user,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=100,
        )

        mapper = BountyMapper()
        interactions = mapper.map_to_interactions(bounty)

        timestamp = interactions[0]["TIMESTAMP"]
        self.assertIsInstance(timestamp, int)
        # Timestamp should be reasonable (after 2020)
        self.assertGreater(timestamp, 1577836800)  # Jan 1, 2020
