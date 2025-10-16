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
        from django.contrib.contenttypes.models import ContentType

        from paper.models import Paper

        self.user = User.objects.create(username="testuser", email="test@example.com")
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
            object_id=1,  # Temporary, will be updated
        )

        # Create a placeholder bounty for escrow reference
        paper_ct = ContentType.objects.get_for_model(Paper)
        temp_bounty = Bounty.objects.create(
            created_by=self.user,
            unified_document=self.unified_doc,
            amount=0,
            escrow=self.escrow,
            item_content_type=paper_ct,
            item_object_id=self.paper.id,
        )

        # Update escrow's object_id to point to bounty
        self.escrow.object_id = temp_bounty.id
        self.escrow.save()

    def test_event_type_name(self):
        """Test event type name property."""
        mapper = BountyMapper()
        self.assertEqual(mapper.event_type_name, "bounty")

    def test_get_queryset_returns_main_bounties_only(self):
        """Test that queryset includes only main bounties (no parent)."""
        from django.contrib.contenttypes.models import ContentType

        from paper.models import Paper

        # Create multiple main bounties
        paper_ct = ContentType.objects.get_for_model(Paper)
        bounty1 = Bounty.objects.create(
            created_by=self.user,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=100,
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

        bounty2 = Bounty.objects.create(
            created_by=self.user,
            unified_document=unified_doc2,
            amount=200,
            escrow=escrow2,
            item_content_type=paper_ct,
            item_object_id=paper2.id,
        )

        escrow2.object_id = bounty2.id
        escrow2.save()

        mapper = BountyMapper()
        queryset = mapper.get_queryset()

        # Should return 3 main bounties (setUp creates 1, this test creates 2 more)
        self.assertEqual(queryset.count(), 3)
        bounty_ids = list(queryset.values_list("id", flat=True))
        self.assertIn(bounty1.id, bounty_ids)
        self.assertIn(bounty2.id, bounty_ids)

    def test_get_queryset_excludes_child_bounties(self):
        """Test that child bounties (contributions) are excluded."""
        from django.contrib.contenttypes.models import ContentType

        from paper.models import Paper

        paper_ct = ContentType.objects.get_for_model(Paper)

        # Create main bounty
        main_bounty = Bounty.objects.create(
            created_by=self.user,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=100,
            item_content_type=paper_ct,
            item_object_id=self.paper.id,
        )

        # Create child bounty (contribution)
        user2 = User.objects.create(username="contributor", email="contrib@example.com")
        Bounty.objects.create(
            created_by=user2,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=50,
            parent=main_bounty,
            item_content_type=paper_ct,
            item_object_id=self.paper.id,
        )

        mapper = BountyMapper()
        queryset = mapper.get_queryset()

        # Should include 2 main bounties (setUp + main_bounty), exclude child
        self.assertEqual(queryset.count(), 2)
        bounty_ids = list(queryset.values_list("id", flat=True))
        self.assertIn(main_bounty.id, bounty_ids)

    def test_get_queryset_with_date_filters(self):
        """Test queryset filtering by date range."""
        from django.contrib.contenttypes.models import ContentType

        from paper.models import Paper

        now = django_timezone.now()
        past_date = now - timedelta(days=10)

        paper_ct = ContentType.objects.get_for_model(Paper)

        # Create bounty in the past
        past_bounty = Bounty.objects.create(
            created_by=self.user,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=100,
            item_content_type=paper_ct,
            item_object_id=self.paper.id,
        )
        past_bounty.created_date = past_date
        past_bounty.save()

        # Create bounty now
        unified_doc2 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        paper2 = Paper.objects.create(
            title="Test Paper 2",
            unified_document=unified_doc2,
            uploaded_by=self.user,
        )

        bounty_ct = ContentType.objects.get_for_model(Bounty)
        escrow2 = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            content_type=bounty_ct,
            object_id=1,  # Temporary
        )

        current_bounty = Bounty.objects.create(
            created_by=self.user,
            unified_document=unified_doc2,
            amount=200,
            escrow=escrow2,
            item_content_type=paper_ct,
            item_object_id=paper2.id,
        )

        escrow2.object_id = current_bounty.id
        escrow2.save()

        mapper = BountyMapper()

        # Filter by start date (includes setUp bounty + current_bounty)
        queryset = mapper.get_queryset(start_date=now - timedelta(days=1))
        self.assertEqual(queryset.count(), 2)
        bounty_ids = list(queryset.values_list("id", flat=True))
        self.assertIn(current_bounty.id, bounty_ids)

        # Filter by end date
        queryset = mapper.get_queryset(end_date=now - timedelta(days=5))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, past_bounty.id)

        # Filter by date range (includes all 3: setUp + past + current)
        queryset = mapper.get_queryset(
            start_date=past_date - timedelta(days=1),
            end_date=now + timedelta(days=1),
        )
        self.assertEqual(queryset.count(), 3)

    def test_map_bounty_to_interaction(self):
        """Test mapping a bounty to BOUNTY_CREATED interaction."""
        from django.contrib.contenttypes.models import ContentType

        from paper.models import Paper

        paper_ct = ContentType.objects.get_for_model(Paper)
        bounty = Bounty.objects.create(
            created_by=self.user,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=100,
            item_content_type=paper_ct,
            item_object_id=self.paper.id,
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

    def test_timestamp_is_integer(self):
        """Test that timestamp is converted to integer epoch seconds."""
        from django.contrib.contenttypes.models import ContentType

        from paper.models import Paper

        paper_ct = ContentType.objects.get_for_model(Paper)
        bounty = Bounty.objects.create(
            created_by=self.user,
            escrow=self.escrow,
            unified_document=self.unified_doc,
            amount=100,
            item_content_type=paper_ct,
            item_object_id=self.paper.id,
        )

        mapper = BountyMapper()
        interactions = mapper.map_to_interactions(bounty)

        timestamp = interactions[0]["TIMESTAMP"]
        self.assertIsInstance(timestamp, int)
        # Timestamp should be reasonable (after 2020)
        self.assertGreater(timestamp, 1577836800)  # Jan 1, 2020
