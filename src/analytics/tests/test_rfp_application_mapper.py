"""
Unit tests for RFP (Grant) application mapper.

Tests the mapping of GrantApplication records to Personalize interactions.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone as django_timezone

from analytics.services.personalize_constants import EVENT_WEIGHTS, RFP_APPLIED
from analytics.services.personalize_mappers.rfp_application_mapper import (
    RfpApplicationMapper,
)
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.grant_model import Grant
from researchhub_document.related_models.constants.document_type import (
    GRANT as GRANT_DOC_TYPE,
)
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class TestRfpApplicationMapper(TestCase):
    """Tests for RfpApplicationMapper class."""

    def setUp(self):
        self.grant_creator = User.objects.create(
            username="grantcreator", email="creator@example.com"
        )
        self.applicant = User.objects.create(
            username="applicant", email="applicant@example.com"
        )

        # Create grant unified document
        self.grant_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT_DOC_TYPE
        )

        # Create grant post
        self.grant_post = ResearchhubPost.objects.create(
            created_by=self.grant_creator,
            unified_document=self.grant_unified_doc,
            document_type=GRANT_DOC_TYPE,
            title="Test Grant",
        )

        # Create grant
        self.grant = Grant.objects.create(
            created_by=self.grant_creator,
            unified_document=self.grant_unified_doc,
            amount=10000,
            description="Test grant description",
        )

        # Create preregistration unified document
        self.prereg_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )

        # Create preregistration post
        self.prereg_post = ResearchhubPost.objects.create(
            created_by=self.applicant,
            unified_document=self.prereg_unified_doc,
            document_type=PREREGISTRATION,
            title="Test Preregistration",
        )

    def test_event_type_name(self):
        """Test event type name property."""
        mapper = RfpApplicationMapper()
        self.assertEqual(mapper.event_type_name, "rfp_application")

    def test_get_queryset_returns_all_applications(self):
        """Test that queryset includes all grant applications."""
        # Create multiple applications
        app1 = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.prereg_post,
            applicant=self.applicant,
        )

        # Create another applicant and application
        applicant2 = User.objects.create(
            username="applicant2", email="applicant2@example.com"
        )
        prereg_unified_doc2 = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        prereg_post2 = ResearchhubPost.objects.create(
            created_by=applicant2,
            unified_document=prereg_unified_doc2,
            document_type=PREREGISTRATION,
            title="Test Preregistration 2",
        )
        app2 = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=prereg_post2,
            applicant=applicant2,
        )

        mapper = RfpApplicationMapper()
        queryset = mapper.get_queryset()

        # Should return all applications
        self.assertEqual(queryset.count(), 2)
        app_ids = list(queryset.values_list("id", flat=True))
        self.assertIn(app1.id, app_ids)
        self.assertIn(app2.id, app_ids)

    def test_get_queryset_with_date_filters(self):
        """Test queryset filtering by date range."""
        now = django_timezone.now()
        past_date = now - timedelta(days=10)

        # Create application in the past
        past_app = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.prereg_post,
            applicant=self.applicant,
        )
        past_app.created_date = past_date
        past_app.save()

        # Create application now
        applicant2 = User.objects.create(
            username="applicant2", email="applicant2@example.com"
        )
        prereg_unified_doc2 = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        prereg_post2 = ResearchhubPost.objects.create(
            created_by=applicant2,
            unified_document=prereg_unified_doc2,
            document_type=PREREGISTRATION,
            title="Test Preregistration 2",
        )
        current_app = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=prereg_post2,
            applicant=applicant2,
        )

        mapper = RfpApplicationMapper()

        # Filter by start date
        queryset = mapper.get_queryset(start_date=now - timedelta(days=1))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, current_app.id)

        # Filter by end date
        queryset = mapper.get_queryset(end_date=now - timedelta(days=5))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, past_app.id)

        # Filter by date range
        queryset = mapper.get_queryset(
            start_date=past_date - timedelta(days=1),
            end_date=now + timedelta(days=1),
        )
        self.assertEqual(queryset.count(), 2)

    def test_map_application_to_interaction(self):
        """Test mapping a grant application to RFP_APPLIED interaction."""
        application = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.prereg_post,
            applicant=self.applicant,
        )

        mapper = RfpApplicationMapper()
        interactions = mapper.map_to_interactions(application)

        # Should create exactly one interaction
        self.assertEqual(len(interactions), 1)

        interaction = interactions[0]
        self.assertEqual(interaction["USER_ID"], str(self.applicant.id))
        self.assertEqual(interaction["ITEM_ID"], str(self.grant_unified_doc.id))
        self.assertEqual(interaction["EVENT_TYPE"], RFP_APPLIED)
        self.assertEqual(interaction["EVENT_VALUE"], EVENT_WEIGHTS[RFP_APPLIED])
        self.assertIsNone(interaction["DEVICE"])
        self.assertIsNone(interaction["IMPRESSION"])
        self.assertIsNone(interaction["RECOMMENDATION_ID"])
        self.assertEqual(
            interaction["TIMESTAMP"],
            datetime_to_epoch_seconds(application.created_date),
        )

    def test_timestamp_is_integer(self):
        """Test that timestamp is converted to integer epoch seconds."""
        application = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.prereg_post,
            applicant=self.applicant,
        )

        mapper = RfpApplicationMapper()
        interactions = mapper.map_to_interactions(application)

        timestamp = interactions[0]["TIMESTAMP"]
        self.assertIsInstance(timestamp, int)
        # Timestamp should be reasonable (after 2020)
        self.assertGreater(timestamp, 1577836800)  # Jan 1, 2020
