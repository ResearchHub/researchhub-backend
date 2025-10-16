"""
Unit tests for Proposal funding mapper.

Tests the mapping of fundraise contribution Purchase records to Personalize
interactions.
"""

from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone as django_timezone

from analytics.services.personalize_constants import EVENT_WEIGHTS, PROPOSAL_FUNDED
from analytics.services.personalize_mappers.proposal_funding_mapper import (
    ProposalFundingMapper,
)
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.purchase_model import Purchase
from reputation.related_models.escrow import Escrow
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class TestProposalFundingMapper(TestCase):
    """Tests for ProposalFundingMapper class."""

    def setUp(self):
        self.fundraise_creator = User.objects.create(
            username="creator", email="creator@example.com"
        )
        self.contributor = User.objects.create(
            username="contributor", email="contributor@example.com"
        )

        # Create proposal unified document
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )

        # Create proposal post
        self.post = ResearchhubPost.objects.create(
            created_by=self.fundraise_creator,
            unified_document=self.unified_doc,
            document_type=PREREGISTRATION,
            title="Test Proposal",
        )

        # Create fundraise first (without escrow)
        self.fundraise = Fundraise.objects.create(
            created_by=self.fundraise_creator,
            unified_document=self.unified_doc,
            goal_amount=10000,
        )

        # Create escrow linked to fundraise
        self.escrow = Escrow.objects.create(
            created_by=self.fundraise_creator,
            hold_type=Escrow.FUNDRAISE,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
        )

        # Link escrow back to fundraise
        self.fundraise.escrow = self.escrow
        self.fundraise.save()

    def test_event_type_name(self):
        """Test event type name property."""
        mapper = ProposalFundingMapper()
        self.assertEqual(mapper.event_type_name, "proposal_funding")

    def test_get_queryset_only_fundraise_contributions(self):
        """Test that queryset includes only FUNDRAISE_CONTRIBUTION purchases."""
        # Create FUNDRAISE_CONTRIBUTION purchase
        contribution = Purchase.objects.create(
            user=self.contributor,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            purchase_method=Purchase.OFF_CHAIN,
            amount="100",
        )

        # Create other purchase types (should be excluded)
        Purchase.objects.create(
            user=self.contributor,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.BOOST,
            purchase_method=Purchase.OFF_CHAIN,
            amount="50",
        )

        mapper = ProposalFundingMapper()
        queryset = mapper.get_queryset()

        # Should only return FUNDRAISE_CONTRIBUTION purchases
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, contribution.id)
        self.assertEqual(
            queryset.first().purchase_type, Purchase.FUNDRAISE_CONTRIBUTION
        )

    def test_get_queryset_with_date_filters(self):
        """Test queryset filtering by date range."""
        now = django_timezone.now()
        past_date = now - timedelta(days=10)

        # Create contribution in the past
        past_contribution = Purchase.objects.create(
            user=self.contributor,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            purchase_method=Purchase.OFF_CHAIN,
            amount="100",
        )
        past_contribution.created_date = past_date
        past_contribution.save()

        # Create contribution now
        current_contribution = Purchase.objects.create(
            user=self.contributor,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            purchase_method=Purchase.OFF_CHAIN,
            amount="200",
        )

        mapper = ProposalFundingMapper()

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
        """Test mapping a fundraise contribution to PROPOSAL_FUNDED interaction."""
        contribution = Purchase.objects.create(
            user=self.contributor,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            purchase_method=Purchase.OFF_CHAIN,
            amount="100",
        )

        mapper = ProposalFundingMapper()
        interactions = mapper.map_to_interactions(contribution)

        # Should create exactly one interaction
        self.assertEqual(len(interactions), 1)

        interaction = interactions[0]
        self.assertEqual(interaction["USER_ID"], str(self.contributor.id))
        self.assertEqual(interaction["ITEM_ID"], str(self.unified_doc.id))
        self.assertEqual(interaction["EVENT_TYPE"], PROPOSAL_FUNDED)
        self.assertEqual(interaction["EVENT_VALUE"], EVENT_WEIGHTS[PROPOSAL_FUNDED])
        self.assertIsNone(interaction["DEVICE"])
        self.assertIsNone(interaction["IMPRESSION"])
        self.assertIsNone(interaction["RECOMMENDATION_ID"])
        self.assertEqual(
            interaction["TIMESTAMP"],
            datetime_to_epoch_seconds(contribution.created_date),
        )

    def test_timestamp_is_integer(self):
        """Test that timestamp is converted to integer epoch seconds."""
        contribution = Purchase.objects.create(
            user=self.contributor,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            purchase_method=Purchase.OFF_CHAIN,
            amount="100",
        )

        mapper = ProposalFundingMapper()
        interactions = mapper.map_to_interactions(contribution)

        timestamp = interactions[0]["TIMESTAMP"]
        self.assertIsInstance(timestamp, int)
        # Timestamp should be reasonable (after 2020)
        self.assertGreater(timestamp, 1577836800)  # Jan 1, 2020
