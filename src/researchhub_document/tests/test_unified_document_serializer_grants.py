from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.test import TestCase

from purchase.models import Grant
from purchase.serializers import DynamicGrantSerializer
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.serializers import DynamicUnifiedDocumentSerializer
from user.tests.helpers import create_random_authenticated_user


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

    def test_get_grants_with_existing_grants(self):
        """Test that grants are properly serialized when they exist"""
        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc, _include_fields=["id", "grants"], context={}
        )
        data = serializer.data

        self.assertIn("grants", data)
        self.assertIsInstance(data["grants"], list)
        self.assertEqual(len(data["grants"]), 2)

        # Check that both grants are included
        grant_ids = {grant["id"] for grant in data["grants"]}
        expected_ids = {self.grant1.id, self.grant2.id}
        self.assertEqual(grant_ids, expected_ids)

    def test_get_grants_with_no_grants(self):
        """Test that empty list is returned when no grants exist"""
        # Create a new unified document without grants
        post_without_grants = create_post(created_by=self.user1, document_type=GRANT)

        serializer = DynamicUnifiedDocumentSerializer(
            post_without_grants.unified_document,
            _include_fields=["id", "grants"],
            context={},
        )
        data = serializer.data

        self.assertIn("grants", data)
        self.assertIsInstance(data["grants"], list)
        self.assertEqual(len(data["grants"]), 0)

    def test_get_grants_with_context_fields(self):
        """Test that context fields are properly applied to grant serialization"""
        context = {
            "doc_duds_get_grants": {
                "_include_fields": [
                    "id",
                    "status",
                    "amount",
                    "organization",
                ]
            }
        }

        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc, _include_fields=["id", "grants"], context=context
        )
        data = serializer.data

        self.assertIn("grants", data)
        self.assertEqual(len(data["grants"]), 2)

        # Check that each grant has the expected fields
        for grant_data in data["grants"]:
            expected_fields = {"id", "status", "amount", "organization"}
            # DynamicGrantSerializer includes all fields by default, but we can check
            # our key fields are there
            self.assertTrue(expected_fields.issubset(set(grant_data.keys())))
            self.assertIn("id", grant_data)
            self.assertIn("status", grant_data)
            self.assertIn("amount", grant_data)
            self.assertIn("organization", grant_data)

    def test_get_grants_with_filter_fields(self):
        """Test that filter fields are properly applied"""
        context = {"doc_duds_get_grants": {"_filter_fields": {"status": Grant.OPEN}}}

        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc, _include_fields=["id", "grants"], context=context
        )
        data = serializer.data

        self.assertIn("grants", data)
        self.assertEqual(len(data["grants"]), 1)
        self.assertEqual(data["grants"][0]["id"], self.grant1.id)
        self.assertEqual(data["grants"][0]["status"], Grant.OPEN)

    def test_get_grants_created_by_context(self):
        """Test that created_by field is properly contextualized"""
        context = {
            "doc_duds_get_grants": {"_include_fields": ["id", "created_by", "status"]},
            "pch_dgs_get_created_by": {
                "_include_fields": ["id", "first_name", "last_name"]
            },
        }

        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc, _include_fields=["id", "grants"], context=context
        )
        data = serializer.data

        self.assertIn("grants", data)
        self.assertEqual(len(data["grants"]), 2)

        # Check that created_by is properly serialized
        for grant_data in data["grants"]:
            self.assertIn("created_by", grant_data)
            created_by = grant_data["created_by"]
            self.assertIn("id", created_by)
            # Note: The actual field names depend on the DynamicGrantSerializer
            # implementation

    def test_grants_field_not_included_when_not_requested(self):
        """Test that grants field is not included when not in _include_fields"""
        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc, _include_fields=["id", "document_type"], context={}
        )
        data = serializer.data

        self.assertNotIn("grants", data)
        self.assertIn("id", data)
        self.assertIn("document_type", data)

    def test_grants_serialization_matches_dynamic_grant_serializer(self):
        """Test that grants are serialized consistently with DynamicGrantSerializer"""
        # Get grants data from unified document serializer
        unified_doc_serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc, _include_fields=["id", "grants"], context={}
        )
        unified_doc_data = unified_doc_serializer.data

        # Get the same grants data directly from DynamicGrantSerializer
        direct_grant_serializer = DynamicGrantSerializer(
            self.unified_doc.grants.all(), many=True, context={}
        )
        direct_grant_data = direct_grant_serializer.data

        # Compare the grants data
        self.assertEqual(len(unified_doc_data["grants"]), len(direct_grant_data))

        # Sort both by id for comparison
        unified_grants = sorted(unified_doc_data["grants"], key=lambda x: x["id"])
        direct_grants = sorted(direct_grant_data, key=lambda x: x["id"])

        for unified_grant, direct_grant in zip(unified_grants, direct_grants):
            self.assertEqual(unified_grant["id"], direct_grant["id"])
            self.assertEqual(unified_grant["amount"], direct_grant["amount"])
            self.assertEqual(
                unified_grant["organization"], direct_grant["organization"]
            )
            self.assertEqual(unified_grant["status"], direct_grant["status"])

    def test_grants_with_multiple_filter_conditions(self):
        """Test grants filtering with multiple conditions"""
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
            "doc_duds_get_grants": {
                "_filter_fields": {
                    "created_by": self.user1,
                    "status__in": [Grant.OPEN, Grant.COMPLETED],
                }
            }
        }

        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc, _include_fields=["id", "grants"], context=context
        )
        data = serializer.data

        self.assertIn("grants", data)
        self.assertEqual(len(data["grants"]), 2)  # grant1 (OPEN) and grant3 (COMPLETED)

        grant_ids = {grant["id"] for grant in data["grants"]}
        expected_ids = {self.grant1.id, grant3.id}
        self.assertEqual(grant_ids, expected_ids)

    def test_grants_field_in_serializer_class(self):
        """Test that grants field is properly defined in the serializer class"""
        serializer = DynamicUnifiedDocumentSerializer()

        # Check that grants field exists in declared_fields (SerializerMethodField)
        self.assertIn("grants", serializer.fields)

        # Check that get_grants method exists
        self.assertTrue(hasattr(serializer, "get_grants"))
        self.assertTrue(callable(getattr(serializer, "get_grants")))

    def test_grants_with_empty_context(self):
        """Test grants serialization with empty context"""
        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc,
            _include_fields=["id", "grants"],
            context={"doc_duds_get_grants": {}},
        )
        data = serializer.data

        self.assertIn("grants", data)
        self.assertEqual(len(data["grants"]), 2)

    def test_grants_with_missing_context_key(self):
        """Test grants serialization when context key is missing"""
        serializer = DynamicUnifiedDocumentSerializer(
            self.unified_doc,
            _include_fields=["id", "grants"],
            context={"some_other_key": {}},
        )
        data = serializer.data

        self.assertIn("grants", data)
        self.assertEqual(len(data["grants"]), 2)
