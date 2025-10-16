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
        from django.contrib.contenttypes.models import ContentType

        from paper.models import Paper

        self.user = User.objects.create(username="creator", email="creator@example.com")
        self.contributor = User.objects.create(
            username="contributor", email="contributor@example.com"
        )
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION"
        )

        # Create paper for bounty item reference
        self.paper = Paper.objects.create(
            title="Test Paper",
            unified_document=self.unified_doc,
            uploaded_by=self.user,
        )

        # Create escrow first with temporary object_id
        bounty_ct = ContentType.objects.get_for_model(Bounty)
        self.escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            content_type=bounty_ct,
            object_id=1,  # Temporary
        )

        # Create main bounty with escrow and item reference
        paper_ct = ContentType.objects.get_for_model(Paper)
        self.main_bounty = Bounty.objects.create(
            created_by=self.user,
            unified_document=self.unified_doc,
            amount=100,
            escrow=self.escrow,
            item_content_type=paper_ct,
            item_object_id=self.paper.id,
        )

        # Update escrow's object_id to point to bounty
        self.escrow.object_id = self.main_bounty.id
        self.escrow.save()

    def test_event_type_name(self):
        """Test event type name property."""
        mapper = BountyContributionMapper()
        self.assertEqual(mapper.event_type_name, "bounty_contribution")

    def test_get_queryset_only_child_bounties(self):
        """Test that queryset includes only child bounties (contributions)."""
        from django.contrib.contenttypes.models import ContentType

        from paper.models import Paper

        # Create child bounties
        paper_ct = ContentType.objects.get_for_model(Paper)
        child_bounty1 = Bounty.objects.create(
            created_by=self.contributor,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=50,
            parent=self.main_bounty,
            item_content_type=paper_ct,
            item_object_id=self.paper.id,
        )

        unified_doc2 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        paper2 = Paper.objects.create(
            title="Test Paper 2",
            unified_document=unified_doc2,
            uploaded_by=self.user,
        )

        # Create escrow first
        bounty_ct = ContentType.objects.get_for_model(Bounty)
        escrow2 = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            content_type=bounty_ct,
            object_id=1,  # Temporary
        )

        main_bounty2 = Bounty.objects.create(
            created_by=self.user,
            unified_document=unified_doc2,
            amount=200,
            escrow=escrow2,
            item_content_type=paper_ct,
            item_object_id=paper2.id,
        )

        escrow2.object_id = main_bounty2.id
        escrow2.save()

        child_bounty2 = Bounty.objects.create(
            created_by=self.contributor,
            escrow=escrow2,
            unified_document=unified_doc2,
            amount=75,
            parent=main_bounty2,
            item_content_type=paper_ct,
            item_object_id=paper2.id,
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
        from django.contrib.contenttypes.models import ContentType

        from paper.models import Paper

        now = django_timezone.now()
        past_date = now - timedelta(days=10)

        paper_ct = ContentType.objects.get_for_model(Paper)

        # Create child bounty in the past
        past_contribution = Bounty.objects.create(
            created_by=self.contributor,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=50,
            parent=self.main_bounty,
            item_content_type=paper_ct,
            item_object_id=self.paper.id,
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
            item_content_type=paper_ct,
            item_object_id=self.paper.id,
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
        from django.contrib.contenttypes.models import ContentType

        from paper.models import Paper

        paper_ct = ContentType.objects.get_for_model(Paper)
        child_bounty = Bounty.objects.create(
            created_by=self.contributor,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=50,
            parent=self.main_bounty,
            item_content_type=paper_ct,
            item_object_id=self.paper.id,
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

    def test_timestamp_is_integer(self):
        """Test that timestamp is converted to integer epoch seconds."""
        from django.contrib.contenttypes.models import ContentType

        from paper.models import Paper

        paper_ct = ContentType.objects.get_for_model(Paper)
        child_bounty = Bounty.objects.create(
            created_by=self.contributor,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=50,
            parent=self.main_bounty,
            item_content_type=paper_ct,
            item_object_id=self.paper.id,
        )

        mapper = BountyContributionMapper()
        interactions = mapper.map_to_interactions(child_bounty)

        timestamp = interactions[0]["TIMESTAMP"]
        self.assertIsInstance(timestamp, int)
        # Timestamp should be reasonable (after 2020)
        self.assertGreater(timestamp, 1577836800)  # Jan 1, 2020
