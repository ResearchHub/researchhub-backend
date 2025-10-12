"""
Unit tests for Bounty contribution mapper.

Tests the mapping of child Bounty records (contributions) to Personalize
interactions.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone as django_timezone

from analytics.services.personalize_constants import BOUNTY_CONTRIBUTED, EVENT_WEIGHTS
from analytics.services.personalize_mappers.bounty_contribution_mapper import (
    BountyContributionMapper,
)
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from reputation.related_models.bounty import Bounty
from reputation.related_models.escrow import Escrow
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class TestBountyContributionMapper(TestCase):
    """Tests for BountyContributionMapper class."""

    def setUp(self):
        self.user = User.objects.create(username="creator", email="creator@example.com")
        self.contributor = User.objects.create(
            username="contributor", email="contributor@example.com"
        )
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION"
        )
        self.escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
        )

        # Create main bounty
        self.main_bounty = Bounty.objects.create(
            created_by=self.user,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=100,
        )

    def test_event_type_name(self):
        """Test event type name property."""
        mapper = BountyContributionMapper()
        self.assertEqual(mapper.event_type_name, "bounty_contribution")

    def test_get_queryset_only_child_bounties(self):
        """Test that queryset includes only child bounties (contributions)."""
        # Create child bounties
        child_bounty1 = Bounty.objects.create(
            created_by=self.contributor,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=50,
            parent=self.main_bounty,
        )

        unified_doc2 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        escrow2 = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
        )
        main_bounty2 = Bounty.objects.create(
            created_by=self.user,
            escrow=escrow2,
            unified_document=unified_doc2,
            amount=200,
        )
        child_bounty2 = Bounty.objects.create(
            created_by=self.contributor,
            escrow=escrow2,
            unified_document=unified_doc2,
            amount=75,
            parent=main_bounty2,
        )

        mapper = BountyContributionMapper()
        queryset = mapper.get_queryset()

        # Should only return child bounties
        self.assertEqual(queryset.count(), 2)
        bounty_ids = list(queryset.values_list("id", flat=True))
        self.assertIn(child_bounty1.id, bounty_ids)
        self.assertIn(child_bounty2.id, bounty_ids)
        # Main bounties should NOT be included
        self.assertNotIn(self.main_bounty.id, bounty_ids)
        self.assertNotIn(main_bounty2.id, bounty_ids)

    def test_get_queryset_with_date_filters(self):
        """Test queryset filtering by date range."""
        now = django_timezone.now()
        past_date = now - timedelta(days=10)

        # Create child bounty in the past
        past_contribution = Bounty.objects.create(
            created_by=self.contributor,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=50,
            parent=self.main_bounty,
        )
        past_contribution.created_date = past_date
        past_contribution.save()

        # Create child bounty now
        current_contribution = Bounty.objects.create(
            created_by=self.contributor,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=75,
            parent=self.main_bounty,
        )

        mapper = BountyContributionMapper()

        # Filter by start date
        queryset = mapper.get_queryset(start_date=now - timedelta(days=1))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, current_contribution.id)

        # Filter by end date
        queryset = mapper.get_queryset(end_date=now - timedelta(days=5))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, past_contribution.id)

        # Filter by date range
        queryset = mapper.get_queryset(
            start_date=past_date - timedelta(days=1),
            end_date=now + timedelta(days=1),
        )
        self.assertEqual(queryset.count(), 2)

    def test_map_contribution_to_interaction(self):
        """Test mapping a bounty contribution to BOUNTY_CONTRIBUTED interaction."""
        child_bounty = Bounty.objects.create(
            created_by=self.contributor,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=50,
            parent=self.main_bounty,
        )

        mapper = BountyContributionMapper()
        interactions = mapper.map_to_interactions(child_bounty)

        # Should create exactly one interaction
        self.assertEqual(len(interactions), 1)

        interaction = interactions[0]
        self.assertEqual(interaction["USER_ID"], str(self.contributor.id))
        self.assertEqual(interaction["ITEM_ID"], str(self.unified_doc.id))
        self.assertEqual(interaction["EVENT_TYPE"], BOUNTY_CONTRIBUTED)
        self.assertEqual(interaction["EVENT_VALUE"], EVENT_WEIGHTS[BOUNTY_CONTRIBUTED])
        self.assertIsNone(interaction["DEVICE"])
        self.assertIsNone(interaction["IMPRESSION"])
        self.assertIsNone(interaction["RECOMMENDATION_ID"])
        self.assertEqual(
            interaction["TIMESTAMP"],
            datetime_to_epoch_seconds(child_bounty.created_date),
        )

    def test_map_contribution_without_unified_doc(self):
        """Test that contributions without unified document are skipped."""
        child_bounty = Bounty.objects.create(
            created_by=self.contributor,
            escrow=self.escrow,
            unified_document=None,
            amount=50,
            parent=self.main_bounty,
        )

        mapper = BountyContributionMapper()
        interactions = mapper.map_to_interactions(child_bounty)

        # Should return empty list
        self.assertEqual(len(interactions), 0)

    def test_map_contribution_without_creator(self):
        """Test that contributions without creator are skipped."""
        child_bounty = Bounty.objects.create(
            created_by=None,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=50,
            parent=self.main_bounty,
        )

        mapper = BountyContributionMapper()
        interactions = mapper.map_to_interactions(child_bounty)

        # Should return empty list
        self.assertEqual(len(interactions), 0)

    def test_timestamp_is_integer(self):
        """Test that timestamp is converted to integer epoch seconds."""
        child_bounty = Bounty.objects.create(
            created_by=self.contributor,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=50,
            parent=self.main_bounty,
        )

        mapper = BountyContributionMapper()
        interactions = mapper.map_to_interactions(child_bounty)

        timestamp = interactions[0]["TIMESTAMP"]
        self.assertIsInstance(timestamp, int)
        # Timestamp should be reasonable (after 2020)
        self.assertGreater(timestamp, 1577836800)  # Jan 1, 2020
