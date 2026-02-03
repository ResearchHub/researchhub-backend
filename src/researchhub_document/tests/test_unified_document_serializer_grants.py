from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from purchase.models import Grant
from purchase.serializers import DynamicGrantSerializer
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.serializers import DynamicUnifiedDocumentSerializer
from researchhub_document.serializers.researchhub_post_serializer import (
    DynamicPostSerializer,
)
from user.tests.helpers import create_random_authenticated_user


class DynamicPostSerializerAbstractTests(TestCase):
    """Test that DynamicPostSerializer returns abstract from renderable_text."""

    def test_abstract_returns_renderable_text(self):
        # Arrange
        user = create_random_authenticated_user("test_user")
        post = create_post(
            created_by=user,
            document_type=PREREGISTRATION,
            renderable_text="This is the project description.",
        )

        # Act
        serializer = DynamicPostSerializer(post, _include_fields=["abstract"])

        # Assert
        self.assertEqual(serializer.data["abstract"], "This is the project description.")


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
            end_date=datetime.now(pytz.UTC) + timedelta(days=30),
        )

    def test_get_grant_with_existing_grant(self):
        """Test that grant is properly serialized when it exists"""
        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc, _include_fields=["id", "grant"], context={}
        )
        data = serializer.data

        self.assertIn("grant", data)
        self.assertIsNotNone(data["grant"])
        self.assertIsInstance(data["grant"], dict)

        # Check that the grant has the expected id (should be the first one found)
        self.assertIn(data["grant"]["id"], [self.grant1.id, self.grant2.id])

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

    def test_get_grant_with_context_fields(self):
        """Test that context fields are properly applied to grant serialization"""
        context = {
            "doc_duds_get_grant": {
                "_include_fields": [
                    "id",
                    "status",
                    "amount",
                    "organization",
                ]
            }
        }

        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc, _include_fields=["id", "grant"], context=context
        )
        data = serializer.data

        self.assertIn("grant", data)
        self.assertIsNotNone(data["grant"])

        # Check that the grant has the expected fields
        grant_data = data["grant"]
        expected_fields = {"id", "status", "amount", "organization"}
        # DynamicGrantSerializer includes all fields by default, but we can check
        # our key fields are there
        self.assertTrue(expected_fields.issubset(set(grant_data.keys())))
        self.assertIn("id", grant_data)
        self.assertIn("status", grant_data)
        self.assertIn("amount", grant_data)
        self.assertIn("organization", grant_data)

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

    def test_get_grant_created_by_context(self):
        """Test that created_by field is properly contextualized"""
        context = {
            "doc_duds_get_grant": {"_include_fields": ["id", "created_by", "status"]},
            "pch_dgs_get_created_by": {
                "_include_fields": ["id", "first_name", "last_name"]
            },
        }

        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc, _include_fields=["id", "grant"], context=context
        )
        data = serializer.data

        self.assertIn("grant", data)
        self.assertIsNotNone(data["grant"])

        # Check that created_by is properly serialized
        grant_data = data["grant"]
        self.assertIn("created_by", grant_data)
        created_by = grant_data["created_by"]
        self.assertIn("id", created_by)
        # Note: The actual field names depend on the DynamicGrantSerializer
        # implementation

    def test_grants_field_not_included_when_not_requested(self):
        """Test that grant field is not included when not in _include_fields"""
        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc, _include_fields=["id", "document_type"], context={}
        )
        data = serializer.data

        self.assertNotIn("grant", data)
        self.assertIn("id", data)
        self.assertIn("document_type", data)

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

    def test_grant_with_multiple_filter_conditions(self):
        """Test grant filtering with multiple conditions"""
        # Create another grant with different status
        grant3 = Grant.objects.create(
            created_by=self.user1,
            unified_document=self.unified_doc,
            amount=Decimal("75000.00"),
            currency="USD",
            organization="Research Institute",
            description="Advanced research grant",
            status=Grant.COMPLETED,
        )

        context = {
            "doc_duds_get_grant": {
                "_filter_fields": {
                    "created_by": self.user1,
                    "status__in": [Grant.OPEN, Grant.COMPLETED],
                }
            }
        }

        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc, _include_fields=["id", "grant"], context=context
        )
        data = serializer.data

        self.assertIn("grant", data)
        self.assertIsNotNone(data["grant"])  # Should return first matching grant

        # Should return one of the filtered grants (grant1 or grant3)
        grant_id = data["grant"]["id"]
        self.assertIn(grant_id, {self.grant1.id, grant3.id})

    def test_grant_field_in_serializer_class(self):
        """Test that grant field is properly defined in the serializer class"""
        serializer = DynamicUnifiedDocumentSerializer()

        # Check that grant field exists in declared_fields (SerializerMethodField)
        self.assertIn("grant", serializer.fields)

        # Check that get_grant method exists
        self.assertTrue(hasattr(serializer, "get_grant"))
        self.assertTrue(callable(getattr(serializer, "get_grant")))

    def test_grant_with_empty_context(self):
        """Test grant serialization with empty context"""
        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc,
            _include_fields=["id", "grant"],
            context={"doc_duds_get_grant": {}},
        )
        data = serializer.data

        self.assertIn("grant", data)
        self.assertIsNotNone(data["grant"])

    def test_grant_with_missing_context_key(self):
        """Test grant serialization when context key is missing"""
        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc,
            _include_fields=["id", "grant"],
            context={"some_other_key": {}},
        )
        data = serializer.data

        self.assertIn("grant", data)
        self.assertIsNotNone(data["grant"])


class ResearchhubPostGrantModeratorTests(APITestCase):
    """Test moderator restrictions for creating GRANT posts with grant data"""

    def setUp(self):
        self.moderator_user = create_random_authenticated_user(
            "moderator", moderator=True
        )
        self.regular_user = create_random_authenticated_user("regular", moderator=False)

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
        """Test that moderators can create GRANT type posts with grant data"""
        self.client.force_authenticate(user=self.moderator_user)

        url = reverse("researchhubpost-list")
        response = self.client.post(url, self.grant_post_data, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertIn("grant", response.data)
        self.assertIsNotNone(response.data["grant"])

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
