from django.contrib.auth import get_user_model
from django.test import TestCase

from organizations.models import NonprofitFundraiseLink, NonprofitOrg
from purchase.models import Fundraise
from researchhub_document.models import ResearchhubUnifiedDocument


class NonprofitOrgModelTests(TestCase):
    """Test cases for the NonprofitOrg model."""

    def setUp(self):
        """Set up test data."""
        self.nonprofit = NonprofitOrg.objects.create(
            name="Test Nonprofit",
            ein="123456789",
            endaoment_org_id="test-org-id",
            base_wallet_address="0x1234567890abcdef1234567890abcdef12345678",
        )

    def test_string_representation(self):
        """Test the string representation of the model."""
        self.assertEqual(str(self.nonprofit), "Test Nonprofit (123456789)")

    def test_string_representation_no_ein(self):
        """Test the string representation when EIN is not provided."""
        nonprofit = NonprofitOrg.objects.create(
            name="No EIN Org",
            endaoment_org_id="no-ein-org",
        )
        self.assertEqual(str(nonprofit), "No EIN Org (No EIN)")

    def test_model_fields(self):
        """Test that all model fields are saved correctly."""
        self.assertEqual(self.nonprofit.name, "Test Nonprofit")
        self.assertEqual(self.nonprofit.ein, "123456789")
        self.assertEqual(self.nonprofit.endaoment_org_id, "test-org-id")
        self.assertEqual(
            self.nonprofit.base_wallet_address,
            "0x1234567890abcdef1234567890abcdef12345678",
        )
        self.assertIsNotNone(self.nonprofit.created_date)
        self.assertIsNotNone(self.nonprofit.updated_date)


class NonprofitFundraiseLinkModelTests(TestCase):
    """Test cases for the NonprofitFundraiseLink model."""

    def setUp(self):
        """Set up test data."""
        # Create a user for the fundraise
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpassword",
        )

        # Create a unified document for the fundraise
        self.document = ResearchhubUnifiedDocument.objects.create()

        # Create the nonprofit
        self.nonprofit = NonprofitOrg.objects.create(
            name="Test Nonprofit",
            ein="123456789",
            endaoment_org_id="test-org-id",
        )

        # Create the fundraise with required fields
        self.fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=self.document,
            goal_amount=1000.00,
        )

        # Create the link
        self.link = NonprofitFundraiseLink.objects.create(
            nonprofit=self.nonprofit,
            fundraise=self.fundraise,
            note="Test note for this link",
        )

    def test_string_representation(self):
        """Test the string representation of the model."""
        expected = f"Test Nonprofit - {self.fundraise.id}"
        self.assertEqual(str(self.link), expected)

    def test_model_fields(self):
        """Test that all model fields are saved correctly."""
        self.assertEqual(self.link.nonprofit, self.nonprofit)
        self.assertEqual(self.link.fundraise, self.fundraise)
        self.assertEqual(self.link.note, "Test note for this link")
        self.assertIsNotNone(self.link.created_date)
        self.assertIsNotNone(self.link.updated_date)

    def test_unique_constraint(self):
        """Test that the unique_together constraint is enforced."""
        # Attempting to create a duplicate link should raise an error
        with self.assertRaises(Exception):
            NonprofitFundraiseLink.objects.create(
                nonprofit=self.nonprofit,
                fundraise=self.fundraise,
                note="Another note",
            )
