from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from organizations.models import NonprofitFundraiseLink, NonprofitOrg
from organizations.services.endaoment_service import (
    EndaomentOrgNotFoundError,
    EndaomentService,
    base_chain_id,
)
from organizations.views import NonprofitFundraiseLinkViewSet
from purchase.models import Fundraise
from researchhub_document.models import ResearchhubUnifiedDocument


class NonprofitFundraiseLinkViewSetTests(APITestCase):
    """Test cases for the NonprofitFundraiseLinkViewSet class."""

    def setUp(self):
        """Set up test data and common variables."""
        # Create a test user
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
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
        self.get_by_fundraise_url = reverse("nonprofit-get-by-fundraise")

        self.endaoment_base_wallet = "0x7ecc1d4936a973ec3b153c0c713e0f71c59abf53"
        self.mock_endaoment_service = MagicMock(spec=EndaomentService)

        patcher = patch.object(
            NonprofitFundraiseLinkViewSet,
            "endaoment_service_class",
            return_value=self.mock_endaoment_service,
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    def _mock_verified_org(
        self, endaoment_org_id, ein="123456789", name="Verified Org"
    ):
        return {
            "id": endaoment_org_id,
            "ein": ein,
            "name": name,
            "deployments": [
                {
                    "chainId": base_chain_id(),
                    "contractAddress": self.endaoment_base_wallet,
                    "isDeployed": True,
                }
            ],
        }

    def test_create_nonprofit_new(self):
        """Test creating a new nonprofit organization."""
        self.mock_endaoment_service.verify_nonprofit_org.return_value = (
            self._mock_verified_org("new-org-id", ein="987654321", name="New Nonprofit")
        )
        data = {
            "ein": "987654321",
            "endaoment_org_id": "new-org-id",
        }

        response = self.client.post(self.create_nonprofit_url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "New Nonprofit")
        self.assertEqual(response.data["ein"], "987654321")
        self.assertEqual(response.data["endaoment_org_id"], "new-org-id")
        self.assertEqual(
            response.data["base_wallet_address"],
            self.endaoment_base_wallet,
        )

        # Verify the nonprofit was created in the database
        nonprofit = NonprofitOrg.objects.get(endaoment_org_id="new-org-id")
        self.assertEqual(nonprofit.name, "New Nonprofit")
        self.assertEqual(nonprofit.base_wallet_address, self.endaoment_base_wallet)
        self.mock_endaoment_service.verify_nonprofit_org.assert_called_once_with(
            "987654321",
            "new-org-id",
        )

    def test_create_nonprofit_existing(self):
        """Test retrieving an existing nonprofit organization."""
        self.mock_endaoment_service.verify_nonprofit_org.return_value = (
            self._mock_verified_org(
                "test-org-id", ein="123456789", name="Endaoment Canonical Name"
            )
        )
        data = {
            "name": "Fake Name From Client",
            "ein": "123456789",
            "endaoment_org_id": "test-org-id",  # This matches the existing nonprofit
        }

        response = self.client.post(self.create_nonprofit_url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Endaoment Canonical Name")
        self.assertEqual(response.data["ein"], "123456789")  # Original EIN
        self.assertEqual(response.data["endaoment_org_id"], "test-org-id")
        self.assertEqual(
            response.data["base_wallet_address"],
            self.endaoment_base_wallet,
        )

    def test_create_nonprofit_ignores_client_name(self):
        """Test that client-provided name is ignored in favor of Endaoment."""
        self.mock_endaoment_service.verify_nonprofit_org.return_value = (
            self._mock_verified_org(
                "new-org-id", ein="987654321", name="Real Nonprofit Name"
            )
        )
        data = {
            "name": "Fake Nonprofit Name",
            "ein": "987654321",
            "endaoment_org_id": "new-org-id",
        }

        response = self.client.post(self.create_nonprofit_url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Real Nonprofit Name")
        nonprofit = NonprofitOrg.objects.get(endaoment_org_id="new-org-id")
        self.assertEqual(nonprofit.name, "Real Nonprofit Name")

    def test_create_nonprofit_missing_required_fields(self):
        """Test validation of required fields."""
        # Missing endaoment_org_id
        data = {
            "ein": "987654321",
        }
        response = self.client.post(self.create_nonprofit_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Missing ein
        data = {
            "endaoment_org_id": "new-org-id",
        }
        response = self.client.post(self.create_nonprofit_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "ein is required")

    def test_create_nonprofit_invalid_ein(self):
        """Test rejection of malformed EIN values."""
        data = {
            "ein": "12345",
            "endaoment_org_id": "new-org-id",
        }
        response = self.client.post(self.create_nonprofit_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "ein must be a valid 9-digit EIN")

    def test_create_nonprofit_not_found_on_endaoment(self):
        """Test rejection when Endaoment has no matching org."""
        self.mock_endaoment_service.verify_nonprofit_org.side_effect = (
            EndaomentOrgNotFoundError()
        )
        data = {
            "ein": "987654321",
            "endaoment_org_id": "fake-org-id",
        }
        response = self.client.post(self.create_nonprofit_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["error"],
            "Nonprofit organization not found on Endaoment",
        )
        self.assertFalse(
            NonprofitOrg.objects.filter(endaoment_org_id="fake-org-id").exists()
        )

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

    def test_link_to_fundraise_rejects_non_owner_create(self):
        """Test that users cannot link nonprofits to another user's fundraise."""
        other_user = self.user_model.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="testpassword",
        )
        other_document = ResearchhubUnifiedDocument.objects.create()
        other_fundraise = Fundraise.objects.create(
            created_by=other_user,
            unified_document=other_document,
            goal_amount=1000.00,
        )
        data = {
            "nonprofit_id": self.nonprofit.id,
            "fundraise_id": other_fundraise.id,
            "note": "Unauthorized note",
        }

        response = self.client.post(self.link_to_fundraise_url, data)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            NonprofitFundraiseLink.objects.filter(fundraise=other_fundraise).exists()
        )

    def test_link_to_fundraise_rejects_non_owner_update(self):
        """Test that users cannot overwrite another user's nonprofit link."""
        other_user = self.user_model.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="testpassword",
        )
        other_document = ResearchhubUnifiedDocument.objects.create()
        other_fundraise = Fundraise.objects.create(
            created_by=other_user,
            unified_document=other_document,
            goal_amount=1000.00,
        )
        replacement_nonprofit = NonprofitOrg.objects.create(
            name="Replacement Nonprofit",
            ein="333333333",
            endaoment_org_id="replacement-org-id",
        )
        link = NonprofitFundraiseLink.objects.create(
            nonprofit=self.nonprofit,
            fundraise=other_fundraise,
            note="Original note",
        )
        data = {
            "nonprofit_id": replacement_nonprofit.id,
            "fundraise_id": other_fundraise.id,
            "note": "Test lagi",
        }

        response = self.client.post(self.link_to_fundraise_url, data)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        link.refresh_from_db()
        self.assertEqual(link.nonprofit_id, self.nonprofit.id)
        self.assertEqual(link.note, "Original note")

    def test_link_to_fundraise_allows_moderator_update(self):
        """Test that moderators can update nonprofit links."""
        moderator = self.user_model.objects.create_user(
            username="moderator",
            email="moderator@example.com",
            password="testpassword",
        )
        moderator.moderator = True
        moderator.save()
        self.client.force_authenticate(user=moderator)
        replacement_nonprofit = NonprofitOrg.objects.create(
            name="Replacement Nonprofit",
            ein="333333333",
            endaoment_org_id="replacement-org-id",
        )
        link = NonprofitFundraiseLink.objects.create(
            nonprofit=self.nonprofit,
            fundraise=self.fundraise,
            note="Original note",
        )
        data = {
            "nonprofit_id": replacement_nonprofit.id,
            "fundraise_id": self.fundraise.id,
            "note": "Moderator note",
        }

        response = self.client.post(self.link_to_fundraise_url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        link.refresh_from_db()
        self.assertEqual(link.nonprofit_id, replacement_nonprofit.id)
        self.assertEqual(link.note, "Moderator note")

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

    def test_get_by_fundraise_success(self):
        """Test retrieving nonprofits linked to a fundraise."""
        # Create a link first
        NonprofitFundraiseLink.objects.create(
            nonprofit=self.nonprofit,
            fundraise=self.fundraise,
            note="Test note",
        )

        # Get nonprofits by fundraise
        response = self.client.get(
            f"{self.get_by_fundraise_url}?fundraise_id={self.fundraise.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["nonprofit"], self.nonprofit.id)
        self.assertEqual(response.data[0]["fundraise"], self.fundraise.id)
        self.assertEqual(response.data[0]["note"], "Test note")

        # Verify nonprofit details are included
        self.assertEqual(response.data[0]["nonprofit_details"]["id"], self.nonprofit.id)
        self.assertEqual(
            response.data[0]["nonprofit_details"]["name"], "Test Nonprofit"
        )
        self.assertEqual(response.data[0]["nonprofit_details"]["ein"], "123456789")

    def test_get_by_fundraise_empty(self):
        """Test retrieving nonprofits when none are linked to the fundraise."""
        # Create a new fundraise with no links
        new_fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=self.document,
            goal_amount=2000.00,
        )

        # Get nonprofits by fundraise
        response = self.client.get(
            f"{self.get_by_fundraise_url}?fundraise_id={new_fundraise.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_get_by_fundraise_missing_id(self):
        """Test that fundraise_id is required."""
        # Missing fundraise_id
        response = self.client.get(self.get_by_fundraise_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_by_fundraise_nonexistent(self):
        """Test retrieving nonprofits for a nonexistent fundraise."""
        # Nonexistent fundraise_id
        response = self.client.get(f"{self.get_by_fundraise_url}?fundraise_id=9999")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_authentication_required(self):
        """Test that authentication is required for the endpoints."""
        # Log out
        self.client.force_authenticate(user=None)

        # Try to create a nonprofit
        data = {
            "name": "New Nonprofit",
            "ein": "987654321",
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

    def test_link_to_fundraise_different_nonprofit(self):
        """Test linking a different nonprofit to a fundraise that already has a link."""
        # Create first nonprofit
        nonprofit1 = NonprofitOrg.objects.create(
            name="First Nonprofit",
            ein="111111111",
            endaoment_org_id="first-org-id",
        )

        # Create second nonprofit
        nonprofit2 = NonprofitOrg.objects.create(
            name="Second Nonprofit",
            ein="222222222",
            endaoment_org_id="second-org-id",
        )

        # Create a link with the first nonprofit
        first_link = NonprofitFundraiseLink.objects.create(
            nonprofit=nonprofit1,
            fundraise=self.fundraise,
            note="First nonprofit note",
        )

        # Try to link the second nonprofit to the same fundraise
        data = {
            "nonprofit_id": nonprofit2.id,
            "fundraise_id": self.fundraise.id,
            "note": "Second nonprofit note",
        }

        response = self.client.post(self.link_to_fundraise_url, data)

        # Verify the response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["nonprofit"], nonprofit2.id)
        self.assertEqual(response.data["fundraise"], self.fundraise.id)
        self.assertEqual(response.data["note"], "Second nonprofit note")

        # Verify only one link exists for this fundraise
        links = NonprofitFundraiseLink.objects.filter(fundraise=self.fundraise)
        self.assertEqual(links.count(), 1)

        # Verify it's the same link (same ID) but with updated content
        updated_link = links.first()
        self.assertEqual(updated_link.id, first_link.id)
        self.assertEqual(updated_link.nonprofit.id, nonprofit2.id)
        self.assertEqual(updated_link.note, "Second nonprofit note")
