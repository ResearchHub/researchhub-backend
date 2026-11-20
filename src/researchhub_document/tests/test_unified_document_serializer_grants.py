from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from purchase.models import Grant
from purchase.serializers import DynamicGrantSerializer
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.serializers import DynamicUnifiedDocumentSerializer
from user.tests.helpers import create_random_authenticated_user, make_user_verified


class DynamicUnifiedDocumentSerializerGrantsTests(TestCase):
    def setUp(self):
        # Create users
        self.user1 = create_random_authenticated_user("grant_user1", moderator=True)
        self.user2 = create_random_authenticated_user("grant_user2", moderator=True)

        # Create a grant post
        self.post = create_post(created_by=self.user1, document_type=GRANT)
        self.unified_doc = self.post.unified_document

        # Create test grants
        self.grant1 = Grant.objects.create(
            created_by=self.user1,
            unified_document=self.unified_doc,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="National Science Foundation",
            description="Research grant for AI applications",
            status=Grant.OPEN,
        )

        self.grant2 = Grant.objects.create(
            created_by=self.user2,
            unified_document=self.unified_doc,
            amount=Decimal("25000.00"),
            currency="USD",
            organization="Tech Innovation Fund",
            description="Seed funding for tech innovation",
            status=Grant.CLOSED,
            end_date=datetime.now(UTC) + timedelta(days=30),
        )

    def test_get_grant_with_no_grant(self):
        """Test that None is returned when no grant exists"""
        # Create a new unified document without grants
        post_without_grants = create_post(created_by=self.user1, document_type=GRANT)

        serializer = DynamicUnifiedDocumentSerializer(
            post_without_grants.unified_document,
            _include_fields=["id", "grant"],
            context={},
        )
        data = serializer.data

        self.assertIn("grant", data)
        self.assertIsNone(data["grant"])

    def test_get_grant_includes_application_visibility(self):
        """application_visibility is serialized when requested in the context"""
        self.grant1.application_visibility = Grant.APPLICATION_VISIBILITY_PRIVATE
        self.grant1.save()

        context = {
            "doc_duds_get_grant": {
                "_include_fields": ["id", "application_visibility"],
                "_filter_fields": {"id": self.grant1.id},
            }
        }

        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc, _include_fields=["id", "grant"], context=context
        )
        grant_data = serializer.data["grant"]

        self.assertIn("application_visibility", grant_data)
        self.assertEqual(
            grant_data["application_visibility"],
            Grant.APPLICATION_VISIBILITY_PRIVATE,
        )

    def test_get_grant_with_filter_fields(self):
        """Test that filter fields are properly applied"""
        context = {"doc_duds_get_grant": {"_filter_fields": {"status": Grant.OPEN}}}

        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc, _include_fields=["id", "grant"], context=context
        )
        data = serializer.data

        self.assertIn("grant", data)
        self.assertIsNotNone(data["grant"])
        self.assertEqual(data["grant"]["id"], self.grant1.id)
        self.assertEqual(data["grant"]["status"], Grant.OPEN)

        # Note: The actual field names depend on the DynamicGrantSerializer
        # implementation

    def test_grant_serialization_matches_dynamic_grant_serializer(self):
        """Test that grant is serialized consistently with DynamicGrantSerializer"""
        # Get grant data from unified document serializer
        unified_doc_serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc, _include_fields=["id", "grant"], context={}
        )
        unified_doc_data = unified_doc_serializer.data

        # Get the first grant data directly from DynamicGrantSerializer
        first_grant = self.unified_doc.grants.first()
        direct_grant_serializer = DynamicGrantSerializer(first_grant, context={})
        direct_grant_data = direct_grant_serializer.data

        # Compare the grant data
        self.assertIsNotNone(unified_doc_data["grant"])
        unified_grant = unified_doc_data["grant"]

        self.assertEqual(unified_grant["id"], direct_grant_data["id"])
        self.assertEqual(unified_grant["amount"], direct_grant_data["amount"])
        self.assertEqual(
            unified_grant["organization"], direct_grant_data["organization"]
        )
        self.assertEqual(unified_grant["status"], direct_grant_data["status"])


class ResearchhubPostGrantModeratorTests(APITestCase):
    """Test moderator restrictions for creating GRANT posts with grant data"""

    def setUp(self):
        self.moderator_user = create_random_authenticated_user(
            "moderator", moderator=True
        )
        self.regular_user = create_random_authenticated_user("regular", moderator=False)
        make_user_verified(self.moderator_user)
        make_user_verified(self.regular_user)

        self.grant_post_data = {
            "title": "Test Grant Post with Grant Data",
            "renderable_text": (
                "This is a test grant post with grant data that should require "
                "moderator permissions"
            ),
            "document_type": GRANT,
            "full_src": "Test full source content",
            "grant_amount": "50000.00",
            "grant_currency": "USD",
            "grant_organization": "Test Foundation",
            "grant_description": "Test grant description",
        }

    def test_moderator_can_create_grant_post_with_grant_data(self):
        """A moderator can publish a grant using blank draft defaults."""
        # Arrange
        self.client.force_authenticate(user=self.moderator_user)
        grant_post_data = {
            **self.grant_post_data,
            "grant_application_visibility": "",
            "grant_currency": "",
        }

        # Act
        url = reverse("researchhubpost-list")
        response = self.client.post(url, grant_post_data, format="json")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertIn("grant", response.data)
        self.assertIsNotNone(response.data["grant"])
        self.assertEqual(response.data["grant"]["currency"], "USD")
        self.assertEqual(
            response.data["grant"]["application_visibility"],
            Grant.APPLICATION_VISIBILITY_OPTIONAL,
        )

    def test_regular_user_can_create_grant_post_without_grant_data(self):
        """Test that regular users can create GRANT type posts without grant data"""
        self.client.force_authenticate(user=self.regular_user)

        post_data_without_grant = self.grant_post_data.copy()
        del post_data_without_grant["grant_amount"]
        del post_data_without_grant["grant_currency"]
        del post_data_without_grant["grant_organization"]
        del post_data_without_grant["grant_description"]

        url = reverse("researchhubpost-list")
        response = self.client.post(url, post_data_without_grant, format="json")

        self.assertEqual(response.status_code, 200)
        # Grant should be None when no grant data is provided
        self.assertIsNone(response.data.get("grant"))
