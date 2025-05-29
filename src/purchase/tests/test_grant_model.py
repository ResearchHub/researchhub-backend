from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.test import TestCase

from purchase.models import Grant
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from user.tests.helpers import create_random_authenticated_user


class GrantModelTests(TestCase):
    def setUp(self):
        # Create a moderator user
        self.user = create_random_authenticated_user("grant_model", moderator=True)

        # Create a grant post
        self.post = create_post(created_by=self.user, document_type=GRANT)

        # Create a grant
        self.grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="National Science Foundation",
            description="Research grant for innovative AI applications in healthcare",
            status=Grant.OPEN,
        )

    def test_grant_creation(self):
        """Test that a grant can be created successfully"""
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=Decimal("25000.00"),
            currency="USD",
            organization="Test Foundation",
            description="Test grant description",
        )

        self.assertIsNotNone(grant.id)
        self.assertEqual(grant.created_by, self.user)
        self.assertEqual(grant.unified_document, self.post.unified_document)
        self.assertEqual(grant.amount, Decimal("25000.00"))
        self.assertEqual(grant.currency, "USD")
        self.assertEqual(grant.organization, "Test Foundation")
        self.assertEqual(grant.description, "Test grant description")
        self.assertEqual(grant.status, Grant.OPEN)  # Default status

    def test_grant_str_representation(self):
        """Test the string representation of a grant"""
        expected = "National Science Foundation - 50000.00 USD"
        self.assertEqual(str(self.grant), expected)

    def test_is_expired_no_end_date(self):
        """Test that a grant with no end date is not expired"""
        self.assertIsNone(self.grant.end_date)
        self.assertFalse(self.grant.is_expired())

    def test_is_expired_future_end_date(self):
        """Test that a grant with a future end date is not expired"""
        future_date = datetime.now(pytz.UTC) + timedelta(days=30)
        self.grant.end_date = future_date
        self.grant.save()

        self.assertFalse(self.grant.is_expired())

    def test_is_expired_past_end_date(self):
        """Test that a grant with a past end date is expired"""
        past_date = datetime.now(pytz.UTC) - timedelta(days=1)
        self.grant.end_date = past_date
        self.grant.save()

        self.assertTrue(self.grant.is_expired())

    def test_is_active_open_not_expired(self):
        """Test that an open grant that's not expired is active"""
        future_date = datetime.now(pytz.UTC) + timedelta(days=30)
        self.grant.end_date = future_date
        self.grant.status = Grant.OPEN
        self.grant.save()

        self.assertTrue(self.grant.is_active())

    def test_is_active_open_expired(self):
        """Test that an open grant that's expired is not active"""
        past_date = datetime.now(pytz.UTC) - timedelta(days=1)
        self.grant.end_date = past_date
        self.grant.status = Grant.OPEN
        self.grant.save()

        self.assertFalse(self.grant.is_active())

    def test_is_active_closed(self):
        """Test that a closed grant is not active"""
        self.grant.status = Grant.CLOSED
        self.grant.save()

        self.assertFalse(self.grant.is_active())

    def test_is_active_completed(self):
        """Test that a completed grant is not active"""
        self.grant.status = Grant.COMPLETED
        self.grant.save()

        self.assertFalse(self.grant.is_active())

    def test_is_active_no_end_date(self):
        """Test that an open grant with no end date is active"""
        self.grant.status = Grant.OPEN
        self.grant.end_date = None
        self.grant.save()

        self.assertTrue(self.grant.is_active())

    def test_grant_status_choices(self):
        """Test that all status choices are valid"""
        # Test OPEN status
        self.grant.status = Grant.OPEN
        self.grant.save()
        self.assertEqual(self.grant.status, Grant.OPEN)

        # Test CLOSED status
        self.grant.status = Grant.CLOSED
        self.grant.save()
        self.assertEqual(self.grant.status, Grant.CLOSED)

        # Test COMPLETED status
        self.grant.status = Grant.COMPLETED
        self.grant.save()
        self.assertEqual(self.grant.status, Grant.COMPLETED)

    def test_grant_amount_precision(self):
        """Test that grant amounts maintain proper decimal precision"""
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=Decimal("12345.67"),
            currency="USD",
            organization="Test Foundation",
            description="Test precision",
        )

        self.assertEqual(grant.amount, Decimal("12345.67"))

    def test_grant_relationships(self):
        """Test that grant relationships work correctly"""
        # Test foreign key to user
        self.assertEqual(self.grant.created_by, self.user)
        self.assertIn(self.grant, self.user.grants.all())

        # Test foreign key to unified document
        self.assertEqual(self.grant.unified_document, self.post.unified_document)
        self.assertIn(self.grant, self.post.unified_document.grants.all())

    def test_grant_defaults(self):
        """Test default values for grant fields"""
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=Decimal("10000.00"),
            organization="Test Org",
            description="Test description",
        )

        # Test default currency
        self.assertEqual(grant.currency, "USD")

        # Test default status
        self.assertEqual(grant.status, Grant.OPEN)

        # Test that start_date is auto-set
        self.assertIsNotNone(grant.start_date)

        # Test that end_date defaults to None
        self.assertIsNone(grant.end_date)

    def test_grant_with_end_date(self):
        """Test creating a grant with an end date"""
        end_date = datetime.now(pytz.UTC) + timedelta(days=60)
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=Decimal("15000.00"),
            currency="USD",
            organization="Test Foundation",
            description="Test grant with deadline",
            end_date=end_date,
        )

        self.assertEqual(grant.end_date, end_date)
        self.assertFalse(grant.is_expired())
        self.assertTrue(grant.is_active())

    def test_multiple_grants_per_user(self):
        """Test that a user can create multiple grants"""
        grant2 = Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=Decimal("75000.00"),
            currency="USD",
            organization="Another Foundation",
            description="Second grant",
        )

        user_grants = self.user.grants.all()
        self.assertEqual(user_grants.count(), 2)
        self.assertIn(self.grant, user_grants)
        self.assertIn(grant2, user_grants)

    def test_grant_meta_indexes(self):
        """Test that the model's indexes are properly configured"""
        # This test ensures that our model's Meta.indexes are defined
        # The actual index creation is tested at the database level
        meta = Grant._meta
        indexes = meta.indexes

        # Check that we have the expected number of indexes
        self.assertEqual(len(indexes), 3)

        # Check that the indexes cover the fields we expect
        index_fields = [list(index.fields) for index in indexes]
        expected_fields = [["status"], ["organization"], ["end_date"]]

        for expected in expected_fields:
            self.assertIn(expected, index_fields)
