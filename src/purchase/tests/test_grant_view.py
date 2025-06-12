from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from rest_framework import status
from rest_framework.test import APITestCase

from purchase.models import Grant, GrantApplication
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.tests.helpers import create_random_authenticated_user


class GrantViewTests(APITestCase):
    def setUp(self):
        # Create users
        self.moderator = create_random_authenticated_user(
            "grant_moderator", moderator=True
        )
        self.regular_user = create_random_authenticated_user("grant_user")

        # Create a grant post
        self.post = create_post(created_by=self.moderator, document_type=GRANT)

        # Create a grant
        self.grant = Grant.objects.create(
            created_by=self.moderator,
            unified_document=self.post.unified_document,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="National Science Foundation",
            description="Research grant for innovative AI applications in healthcare",
            status=Grant.OPEN,
        )

        # Create a preregistration post for testing applications
        self.preregistration_post = create_post(
            created_by=self.regular_user,
            document_type=PREREGISTRATION,
            title="Test Preregistration for Grant Application",
        )

    def test_list_grants_authenticated(self):
        """Test that authenticated users can list grants"""
        self.client.force_authenticate(self.regular_user)
        response = self.client.get("/api/grant/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["organization"], "National Science Foundation"
        )

    def test_list_grants_unauthenticated(self):
        """Test that unauthenticated users cannot list grants"""
        response = self.client.get("/api/grant/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve_grant_authenticated(self):
        """Test that authenticated users can retrieve a specific grant"""
        self.client.force_authenticate(self.regular_user)
        response = self.client.get(f"/api/grant/{self.grant.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["organization"], "National Science Foundation")
        self.assertEqual(response.data["amount"]["usd"], 50000.0)

    def test_create_grant_as_moderator(self):
        """Test that moderators can create grants"""
        self.client.force_authenticate(self.moderator)

        # Create another post for the new grant
        new_post = create_post(created_by=self.moderator, document_type=GRANT)

        grant_data = {
            "unified_document_id": new_post.unified_document.id,
            "amount": "25000.00",
            "currency": "USD",
            "organization": "Test Foundation",
            "description": "Test grant for research purposes",
        }

        response = self.client.post("/api/grant/", grant_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["organization"], "Test Foundation")
        self.assertEqual(response.data["amount"]["usd"], 25000.0)

        # Verify grant was created in database
        grant = Grant.objects.get(id=response.data["id"])
        self.assertEqual(grant.organization, "Test Foundation")
        self.assertEqual(grant.amount, Decimal("25000.00"))

    def test_create_grant_as_regular_user(self):
        """Test that regular users cannot create grants"""
        self.client.force_authenticate(self.regular_user)

        grant_data = {
            "unified_document_id": self.post.unified_document.id,
            "amount": "25000.00",
            "currency": "USD",
            "organization": "Test Foundation",
            "description": "Test grant",
        }

        response = self.client.post("/api/grant/", grant_data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_grant_with_end_date(self):
        """Test creating a grant with an end date"""
        self.client.force_authenticate(self.moderator)

        new_post = create_post(created_by=self.moderator, document_type=GRANT)
        end_date = datetime.now(pytz.UTC) + timedelta(days=60)

        grant_data = {
            "unified_document_id": new_post.unified_document.id,
            "amount": "30000.00",
            "currency": "USD",
            "organization": "Deadline Foundation",
            "description": "Grant with deadline",
            "end_date": end_date.isoformat(),
        }

        response = self.client.post("/api/grant/", grant_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(response.data["end_date"])

    def test_create_grant_invalid_data(self):
        """Test creating a grant with invalid data"""
        self.client.force_authenticate(self.moderator)

        # Test with missing required fields
        grant_data = {
            "amount": "25000.00",
            # Missing unified_document_id, organization, description
        }

        response = self.client.post("/api/grant/", grant_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_grant_invalid_amount(self):
        """Test creating a grant with invalid amount"""
        self.client.force_authenticate(self.moderator)

        new_post = create_post(created_by=self.moderator, document_type=GRANT)

        grant_data = {
            "unified_document_id": new_post.unified_document.id,
            "amount": "-1000.00",  # Negative amount
            "currency": "USD",
            "organization": "Test Foundation",
            "description": "Test grant",
        }

        response = self.client.post("/api/grant/", grant_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_grant_as_creator(self):
        """Test that grant creators can update their grants"""
        self.client.force_authenticate(self.moderator)

        update_data = {
            "description": "Updated grant description",
            "amount": "60000.00",
        }

        response = self.client.patch(f"/api/grant/{self.grant.id}/", update_data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["description"], "Updated grant description")

        # Verify in database
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.description, "Updated grant description")

    def test_update_grant_as_non_creator(self):
        """Test that non-creators cannot update grants"""
        self.client.force_authenticate(self.regular_user)

        update_data = {
            "description": "Unauthorized update",
        }

        response = self.client.patch(f"/api/grant/{self.grant.id}/", update_data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_grant_as_moderator(self):
        """Test that moderators can delete grants"""
        self.client.force_authenticate(self.moderator)

        response = self.client.delete(f"/api/grant/{self.grant.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify grant was deleted
        self.assertFalse(Grant.objects.filter(id=self.grant.id).exists())

    def test_delete_grant_as_regular_user(self):
        """Test that regular users cannot delete grants"""
        self.client.force_authenticate(self.regular_user)

        response = self.client.delete(f"/api/grant/{self.grant.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_close_grant_action(self):
        """Test the close grant action"""
        self.client.force_authenticate(self.moderator)

        response = self.client.post(f"/api/grant/{self.grant.id}/close/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], Grant.CLOSED)

        # Verify in database
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.status, Grant.CLOSED)

    def test_close_grant_already_closed(self):
        """Test closing a grant that's already closed"""
        self.grant.status = Grant.CLOSED
        self.grant.save()

        self.client.force_authenticate(self.moderator)
        response = self.client.post(f"/api/grant/{self.grant.id}/close/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already closed", response.data["message"])

    def test_complete_grant_action(self):
        """Test the complete grant action"""
        self.client.force_authenticate(self.moderator)

        response = self.client.post(f"/api/grant/{self.grant.id}/complete/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], Grant.COMPLETED)

        # Verify in database
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.status, Grant.COMPLETED)

    def test_complete_grant_already_completed(self):
        """Test completing a grant that's already completed"""
        self.grant.status = Grant.COMPLETED
        self.grant.save()

        self.client.force_authenticate(self.moderator)
        response = self.client.post(f"/api/grant/{self.grant.id}/complete/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already completed", response.data["message"])

    def test_reopen_grant_action(self):
        """Test the reopen grant action"""
        self.grant.status = Grant.CLOSED
        self.grant.save()

        self.client.force_authenticate(self.moderator)
        response = self.client.post(f"/api/grant/{self.grant.id}/reopen/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], Grant.OPEN)

        # Verify in database
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.status, Grant.OPEN)

    def test_reopen_grant_already_open(self):
        """Test reopening a grant that's already open"""
        self.client.force_authenticate(self.moderator)
        response = self.client.post(f"/api/grant/{self.grant.id}/reopen/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already open", response.data["message"])

    def test_grant_actions_permission_denied(self):
        """Test that regular users cannot perform grant actions"""
        self.client.force_authenticate(self.regular_user)

        # Test close action
        response = self.client.post(f"/api/grant/{self.grant.id}/close/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Test complete action
        response = self.client.post(f"/api/grant/{self.grant.id}/complete/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Test reopen action
        response = self.client.post(f"/api/grant/{self.grant.id}/reopen/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_grant_serializer_context_fields(self):
        """Test that the grant serializer includes the expected context fields"""
        self.client.force_authenticate(self.regular_user)
        response = self.client.get(f"/api/grant/{self.grant.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check that created_by field is properly serialized
        self.assertIn("created_by", response.data)
        self.assertEqual(response.data["created_by"]["id"], self.moderator.id)

        # Check that amount field includes conversion
        self.assertIn("amount", response.data)
        self.assertIn("usd", response.data["amount"])
        self.assertIn("rsc", response.data["amount"])
        self.assertIn("formatted", response.data["amount"])

        # Check status fields
        self.assertIn("is_expired", response.data)
        self.assertIn("is_active", response.data)

    def test_apply_to_grant_success(self):
        """Test successfully applying to a grant with a preregistration post"""
        self.client.force_authenticate(self.regular_user)

        apply_data = {"preregistration_post_id": self.preregistration_post.id}

        response = self.client.post(
            f"/api/grant/{self.grant.id}/application/", apply_data
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["message"], "Application submitted")

        # Verify application was created in database
        application = GrantApplication.objects.get(
            grant=self.grant,
            preregistration_post=self.preregistration_post,
            applicant=self.regular_user,
        )
        self.assertIsNotNone(application)

    def test_apply_to_grant_duplicate_application(self):
        """Test applying to the same grant twice returns already applied message"""
        self.client.force_authenticate(self.regular_user)

        # First application
        GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.preregistration_post,
            applicant=self.regular_user,
        )

        apply_data = {"preregistration_post_id": self.preregistration_post.id}

        response = self.client.post(
            f"/api/grant/{self.grant.id}/application/", apply_data
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Already applied")

    def test_apply_to_grant_unauthenticated(self):
        """Test that unauthenticated users cannot apply to grants"""
        apply_data = {"preregistration_post_id": self.preregistration_post.id}

        response = self.client.post(
            f"/api/grant/{self.grant.id}/application/", apply_data
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_apply_to_grant_invalid_post_id(self):
        """Test applying with an invalid preregistration post ID"""
        self.client.force_authenticate(self.regular_user)

        apply_data = {"preregistration_post_id": 99999}  # Non-existent ID

        response = self.client.post(
            f"/api/grant/{self.grant.id}/application/", apply_data
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Invalid preregistration post")

    def test_apply_to_grant_not_owner_of_post(self):
        """Test applying with a preregistration post not owned by the user"""
        other_user = create_random_authenticated_user("other_user")
        other_preregistration = create_post(
            created_by=other_user,
            document_type=PREREGISTRATION,
            title="Other User's Preregistration",
        )

        self.client.force_authenticate(self.regular_user)

        apply_data = {"preregistration_post_id": other_preregistration.id}

        response = self.client.post(
            f"/api/grant/{self.grant.id}/application/", apply_data
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Invalid preregistration post")

    def test_apply_to_grant_wrong_document_type(self):
        """Test applying with a post that's not a preregistration"""
        discussion_post = create_post(
            created_by=self.regular_user,
            document_type="DISCUSSION",
            title="Regular Discussion Post",
        )

        self.client.force_authenticate(self.regular_user)

        apply_data = {"preregistration_post_id": discussion_post.id}

        response = self.client.post(
            f"/api/grant/{self.grant.id}/application/", apply_data
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Invalid preregistration post")

    def test_apply_to_closed_grant(self):
        """Test applying to a closed grant"""
        self.grant.status = Grant.CLOSED
        self.grant.save()

        self.client.force_authenticate(self.regular_user)

        apply_data = {"preregistration_post_id": self.preregistration_post.id}

        response = self.client.post(
            f"/api/grant/{self.grant.id}/application/", apply_data
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["error"], "Grant is no longer accepting applications"
        )

    def test_apply_to_expired_grant(self):
        """Test applying to an expired grant"""
        # Set end_date to yesterday
        yesterday = datetime.now(pytz.UTC) - timedelta(days=1)
        self.grant.end_date = yesterday
        self.grant.save()

        self.client.force_authenticate(self.regular_user)

        apply_data = {"preregistration_post_id": self.preregistration_post.id}

        response = self.client.post(
            f"/api/grant/{self.grant.id}/application/", apply_data
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["error"], "Grant is no longer accepting applications"
        )

    def test_apply_to_grant_missing_post_id(self):
        """Test applying without providing a preregistration post ID"""
        self.client.force_authenticate(self.regular_user)

        apply_data = {}  # Missing preregistration_post_id

        response = self.client.post(
            f"/api/grant/{self.grant.id}/application/", apply_data
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Invalid preregistration post")

    def test_apply_to_nonexistent_grant(self):
        """Test applying to a grant that doesn't exist"""
        self.client.force_authenticate(self.regular_user)

        apply_data = {"preregistration_post_id": self.preregistration_post.id}

        response = self.client.post("/api/grant/99999/application/", apply_data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_grant_without_organization(self):
        """Test that grants can be created without an organization"""
        self.client.force_authenticate(self.moderator)

        new_post = create_post(created_by=self.moderator, document_type=GRANT)

        grant_data = {
            "unified_document_id": new_post.unified_document.id,
            "amount": "25000.00",
            "currency": "USD",
            "description": "Test grant without organization",
        }

        response = self.client.post("/api/grant/", grant_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data.get("organization"))
        self.assertEqual(response.data["amount"]["usd"], 25000.0)

        # Verify grant was created in database
        grant = Grant.objects.get(id=response.data["id"])
        self.assertIsNone(grant.organization)

    def test_create_grant_with_contacts(self):
        """Test creating a grant with contact users"""
        self.client.force_authenticate(self.moderator)

        contact_user = create_random_authenticated_user("contact_user")
        new_post = create_post(created_by=self.moderator, document_type=GRANT)

        grant_data = {
            "unified_document_id": new_post.unified_document.id,
            "amount": "25000.00",
            "currency": "USD",
            "organization": "Test Foundation",
            "description": "Test grant with contacts",
            "contact_ids": [contact_user.id, self.moderator.id],
        }

        response = self.client.post("/api/grant/", grant_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["contacts"]), 2)

        # Verify contacts were set in database
        grant = Grant.objects.get(id=response.data["id"])
        self.assertEqual(grant.contacts.count(), 2)
        self.assertIn(contact_user, grant.contacts.all())
        self.assertIn(self.moderator, grant.contacts.all())

    def test_create_grant_with_invalid_contacts(self):
        """Test creating a grant with invalid contact user IDs"""
        self.client.force_authenticate(self.moderator)

        new_post = create_post(created_by=self.moderator, document_type=GRANT)

        grant_data = {
            "unified_document_id": new_post.unified_document.id,
            "amount": "25000.00",
            "currency": "USD",
            "organization": "Test Foundation",
            "description": "Test grant with invalid contacts",
            "contact_ids": [99999, 99998],  # Non-existent user IDs
        }

        response = self.client.post("/api/grant/", grant_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("contact users do not exist", str(response.data))

    def test_grant_str_method_with_organization(self):
        """Test grant string representation with organization"""
        grant_str = str(self.grant)
        self.assertEqual(grant_str, "National Science Foundation - 50000.00 USD")

    def test_grant_str_method_without_organization(self):
        """Test grant string representation without organization"""
        grant_without_org = Grant.objects.create(
            created_by=self.moderator,
            unified_document=self.post.unified_document,
            amount=Decimal("30000.00"),
            currency="USD",
            organization=None,
            description="Grant without organization",
        )
        grant_str = str(grant_without_org)
        self.assertEqual(grant_str, "Unknown Organization - 30000.00 USD")
