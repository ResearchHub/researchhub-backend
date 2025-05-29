from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from purchase.models import Grant
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
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
