from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from organizations.models import NonprofitFundraiseLink, NonprofitOrg
from purchase.models import Fundraise
from researchhub_document.models import ResearchhubUnifiedDocument


class NonprofitFundraiseLinkViewSetTests(APITestCase):
    """Test cases for the NonprofitFundraiseLinkViewSet class."""

    def setUp(self):
        """Set up test data and common variables."""
        # Create a test user
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpassword",
        )
        self.client.force_authenticate(user=self.user)

        # Create a unified document for the fundraise
        self.document = ResearchhubUnifiedDocument.objects.create()

        # Create a fundraise
        self.fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=self.document,
            goal_amount=1000.00,
        )

        # Create a nonprofit
        self.nonprofit = NonprofitOrg.objects.create(
            name="Test Nonprofit",
            ein="123456789",
            endaoment_org_id="test-org-id",
            base_wallet_address="0x1234567890abcdef1234567890abcdef12345678",
        )

        # URLs for the API endpoints
        self.create_nonprofit_url = reverse("nonprofit-create")
        self.link_to_fundraise_url = reverse("nonprofit-link-to-fundraise")

    def test_create_nonprofit_new(self):
        """Test creating a new nonprofit organization."""
        data = {
            "name": "New Nonprofit",
            "ein": "987654321",
            "endaoment_org_id": "new-org-id",
            "base_wallet_address": "0x0987654321fedcba0987654321fedcba09876543",
        }

        response = self.client.post(self.create_nonprofit_url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "New Nonprofit")
        self.assertEqual(response.data["ein"], "987654321")
        self.assertEqual(response.data["endaoment_org_id"], "new-org-id")
        self.assertEqual(
            response.data["base_wallet_address"],
            "0x0987654321fedcba0987654321fedcba09876543",
        )

        # Verify the nonprofit was created in the database
        nonprofit = NonprofitOrg.objects.get(endaoment_org_id="new-org-id")
        self.assertEqual(nonprofit.name, "New Nonprofit")

    def test_create_nonprofit_existing(self):
        """Test retrieving an existing nonprofit organization."""
        data = {
            "name": "Different Name",  # This should update the name
            "endaoment_org_id": "test-org-id",  # This matches the existing nonprofit
        }

        response = self.client.post(self.create_nonprofit_url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Different Name")  # Updated name
        self.assertEqual(response.data["ein"], "123456789")  # Original EIN
        self.assertEqual(response.data["endaoment_org_id"], "test-org-id")

    def test_create_nonprofit_missing_required_fields(self):
        """Test validation of required fields."""
        # Missing name
        data = {
            "endaoment_org_id": "new-org-id",
        }
        response = self.client.post(self.create_nonprofit_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Missing endaoment_org_id
        data = {
            "name": "New Nonprofit",
        }
        response = self.client.post(self.create_nonprofit_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_link_to_fundraise_new(self):
        """Test creating a new link between a nonprofit and a fundraise."""
        data = {
            "nonprofit_id": self.nonprofit.id,
            "fundraise_id": self.fundraise.id,
            "note": "Test note for the link",
        }

        response = self.client.post(self.link_to_fundraise_url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["nonprofit"], self.nonprofit.id)
        self.assertEqual(response.data["fundraise"], self.fundraise.id)
        self.assertEqual(response.data["note"], "Test note for the link")

        # Verify the link was created in the database
        link = NonprofitFundraiseLink.objects.get(
            nonprofit=self.nonprofit, fundraise=self.fundraise
        )
        self.assertEqual(link.note, "Test note for the link")

    def test_link_to_fundraise_existing(self):
        """Test updating an existing link between a nonprofit and a fundraise."""
        # Create a link first
        link = NonprofitFundraiseLink.objects.create(
            nonprofit=self.nonprofit,
            fundraise=self.fundraise,
            note="Original note",
        )

        # Update the link
        data = {
            "nonprofit_id": self.nonprofit.id,
            "fundraise_id": self.fundraise.id,
            "note": "Updated note",
        }

        response = self.client.post(self.link_to_fundraise_url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["note"], "Updated note")

        # Verify the link was updated in the database
        link.refresh_from_db()
        self.assertEqual(link.note, "Updated note")

    def test_link_to_fundraise_missing_required_fields(self):
        """Test validation of required fields."""
        # Missing nonprofit_id
        data = {
            "fundraise_id": self.fundraise.id,
        }
        response = self.client.post(self.link_to_fundraise_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Missing fundraise_id
        data = {
            "nonprofit_id": self.nonprofit.id,
        }
        response = self.client.post(self.link_to_fundraise_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_link_to_fundraise_nonexistent_nonprofit(self):
        """Test linking with a nonexistent nonprofit."""
        data = {
            "nonprofit_id": 9999,  # Nonexistent ID
            "fundraise_id": self.fundraise.id,
        }
        response = self.client.post(self.link_to_fundraise_url, data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_link_to_fundraise_nonexistent_fundraise(self):
        """Test linking with a nonexistent fundraise."""
        data = {
            "nonprofit_id": self.nonprofit.id,
            "fundraise_id": 9999,  # Nonexistent ID
        }
        response = self.client.post(self.link_to_fundraise_url, data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_authentication_required(self):
        """Test that authentication is required for the endpoints."""
        # Log out
        self.client.force_authenticate(user=None)

        # Try to create a nonprofit
        data = {
            "name": "New Nonprofit",
            "endaoment_org_id": "new-org-id",
        }
        response = self.client.post(self.create_nonprofit_url, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Try to link to a fundraise
        data = {
            "nonprofit_id": self.nonprofit.id,
            "fundraise_id": self.fundraise.id,
        }
        response = self.client.post(self.link_to_fundraise_url, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
