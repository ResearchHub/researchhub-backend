"""
Unit tests for Proposal (Preregistration) mapper.

Tests the mapping of Preregistration ResearchhubPost to Personalize interactions.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone as django_timezone

from analytics.services.personalize_constants import EVENT_WEIGHTS, PROPOSAL_CREATED
from analytics.services.personalize_mappers.proposal_mapper import ProposalMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class TestProposalMapper(TestCase):
    """Tests for ProposalMapper class."""

    def setUp(self):
        self.user = User.objects.create(username="testuser", email="test@example.com")
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )

    def test_event_type_name(self):
        """Test event type name property."""
        mapper = ProposalMapper()
        self.assertEqual(mapper.event_type_name, "proposal")

    def test_get_queryset_filters_by_preregistration_type(self):
        """Test that queryset only includes PREREGISTRATION type posts."""
        # Create PREREGISTRATION post
        proposal_post = ResearchhubPost.objects.create(
            title="Test Proposal",
            document_type=PREREGISTRATION,
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

        mapper = ProposalMapper()
        queryset = mapper.get_queryset()

        # Should only return proposal post
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, proposal_post.id)
        self.assertEqual(queryset.first().document_type, PREREGISTRATION)

    def test_get_queryset_with_date_filters(self):
        """Test queryset filtering by date range."""
        now = django_timezone.now()
        past_date = now - timedelta(days=10)

        # Create proposal in the past
        past_proposal = ResearchhubPost.objects.create(
            title="Past Proposal",
            document_type=PREREGISTRATION,
            unified_document=self.unified_doc,
            created_by=self.user,
        )
        past_proposal.created_date = past_date
        past_proposal.save()

        # Create proposal now
        unified_doc2 = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        current_proposal = ResearchhubPost.objects.create(
            title="Current Proposal",
            document_type=PREREGISTRATION,
            unified_document=unified_doc2,
            created_by=self.user,
        )

        mapper = ProposalMapper()

        # Filter by start date
        queryset = mapper.get_queryset(start_date=now - timedelta(days=1))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, current_proposal.id)

        # Filter by end date
        queryset = mapper.get_queryset(end_date=now - timedelta(days=5))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, past_proposal.id)

        # Filter by date range
        queryset = mapper.get_queryset(
            start_date=past_date - timedelta(days=1),
            end_date=now + timedelta(days=1),
        )
        self.assertEqual(queryset.count(), 2)

    def test_map_proposal_to_interaction(self):
        """Test mapping a proposal post to PROPOSAL_CREATED interaction."""
        proposal_post = ResearchhubPost.objects.create(
            title="Test Proposal",
            document_type=PREREGISTRATION,
            unified_document=self.unified_doc,
            created_by=self.user,
        )

        mapper = ProposalMapper()
        interactions = mapper.map_to_interactions(proposal_post)

        # Should create exactly one interaction
        self.assertEqual(len(interactions), 1)

        interaction = interactions[0]
        self.assertEqual(interaction["USER_ID"], str(self.user.id))
        self.assertEqual(interaction["ITEM_ID"], str(self.unified_doc.id))
        self.assertEqual(interaction["EVENT_TYPE"], PROPOSAL_CREATED)
        self.assertEqual(interaction["EVENT_VALUE"], EVENT_WEIGHTS[PROPOSAL_CREATED])
        self.assertIsNone(interaction["DEVICE"])
        self.assertIsNone(interaction["IMPRESSION"])
        self.assertIsNone(interaction["RECOMMENDATION_ID"])
        self.assertEqual(
            interaction["TIMESTAMP"],
            datetime_to_epoch_seconds(proposal_post.created_date),
        )

    def test_timestamp_is_integer(self):
        """Test that timestamp is converted to integer epoch seconds."""
        proposal_post = ResearchhubPost.objects.create(
            title="Test Proposal",
            document_type=PREREGISTRATION,
            unified_document=self.unified_doc,
            created_by=self.user,
        )

        mapper = ProposalMapper()
        interactions = mapper.map_to_interactions(proposal_post)

        timestamp = interactions[0]["TIMESTAMP"]
        self.assertIsInstance(timestamp, int)
        # Timestamp should be reasonable (after 2020)
        self.assertGreater(timestamp, 1577836800)  # Jan 1, 2020
