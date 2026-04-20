from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytz
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from discussion.models import Flag
from feed.views.grant_cache_mixin import GrantCacheMixin
from notification.models import Notification
from purchase.models import Grant, GrantApplication
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.services.grant_service import GrantModerationService
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.related_models.verdict_model import Verdict
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
        """Test that regular users can create grants (they start as PENDING)"""
        self.client.force_authenticate(self.regular_user)

        new_post = create_post(created_by=self.regular_user, document_type=GRANT)
        grant_data = {
            "unified_document_id": new_post.unified_document.id,
            "amount": "25000.00",
            "currency": "USD",
            "organization": "Test Foundation",
            "description": "Test grant",
        }

        response = self.client.post("/api/grant/", grant_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], Grant.PENDING)

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

    def test_short_title_returned_in_serializer(self):
        """Test that short_title is included in the grant serializer response"""
        self.grant.short_title = "AI Healthcare Grant"
        self.grant.save()

        self.client.force_authenticate(self.regular_user)
        response = self.client.get(f"/api/grant/{self.grant.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["short_title"], "AI Healthcare Grant")

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

    def test_create_grant_non_usd_currency_rejected(self):
        # Arrange
        self.client.force_authenticate(self.moderator)
        post = create_post(created_by=self.moderator, document_type=GRANT)

        # Act
        response = self.client.post(
            "/api/grant/",
            {
                "unified_document_id": post.unified_document.id,
                "amount": "10000.00",
                "currency": "EUR",
                "organization": "Euro Org",
                "description": "Non-USD grant",
            },
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_apply_to_pending_grant_rejected(self):
        # Arrange
        post = create_post(created_by=self.moderator, document_type=GRANT)
        pending_grant = Grant.objects.create(
            created_by=self.moderator,
            unified_document=post.unified_document,
            amount=Decimal("5000.00"),
            currency="USD",
            description="Pending grant",
        )
        self.client.force_authenticate(self.regular_user)

        # Act
        response = self.client.post(
            f"/api/grant/{pending_grant.id}/application/",
            {"preregistration_post_id": self.preregistration_post.id},
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["error"], "Grant is no longer accepting applications"
        )


class GrantCacheInvalidationTests(APITestCase):

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_invalidate_clears_grant_feed_caches(self):
        cache_keys = [
            "grants_feed:popular:all:all:none:1-20::",
            "grants_feed:popular:all:all:none:1-20:OPEN:",
            "grants_feed:popular:all:all:none:2-20-newest::",
            "grants_feed:popular:all:all:none:3-20-upvotes:CLOSED:",
        ]

        for key in cache_keys:
            cache.set(key, {"test": "data"})

        GrantCacheMixin.invalidate_grant_feed_cache()

        for key in cache_keys:
            self.assertIsNone(cache.get(key))

    def test_invalidate_does_not_affect_other_caches(self):
        other_key = "feed:popular:all:all:none:1-20"
        cache.set(other_key, {"other": "data"})

        GrantCacheMixin.invalidate_grant_feed_cache()

        self.assertIsNotNone(cache.get(other_key))


class AvailableFundingTests(APITestCase):
    EXCHANGE_RATE = 0.5

    def setUp(self):
        cache.clear()
        self.moderator = create_random_authenticated_user(
            "funding_moderator", moderator=True
        )
        RscExchangeRate.objects.create(
            rate=self.EXCHANGE_RATE, real_rate=self.EXCHANGE_RATE, target_currency="USD"
        )
        self.post1 = create_post(created_by=self.moderator, document_type=GRANT)
        self.post2 = create_post(created_by=self.moderator, document_type=GRANT)

    def tearDown(self):
        cache.clear()

    def _create_grant(self, amount, status_val=Grant.OPEN, end_date=None, post=None):
        post = post or create_post(created_by=self.moderator, document_type=GRANT)
        grant = Grant.objects.create(
            created_by=self.moderator,
            unified_document=post.unified_document,
            amount=Decimal(str(amount)),
            currency="USD",
            description="test",
            status=status_val,
        )
        if end_date is not None:
            Grant.objects.filter(pk=grant.pk).update(end_date=end_date)
        return grant

    def test_sums_multiple_open_grants(self):
        self._create_grant("20000.00", post=self.post1)
        self._create_grant("30000.00", post=self.post2)

        response = self.client.get("/api/grant/available_funding/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["available_funding_in_usd"], 50000.0)
        expected_rsc = round(50000.0 / self.EXCHANGE_RATE, 2)
        self.assertEqual(response.data["available_funding_in_rsc"], expected_rsc)

    def test_excludes_closed_and_completed_grants(self):
        self._create_grant("10000.00", post=self.post1)
        self._create_grant("20000.00", status_val=Grant.CLOSED)
        self._create_grant("30000.00", status_val=Grant.COMPLETED)

        response = self.client.get("/api/grant/available_funding/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["available_funding_in_usd"], 10000.0)

    def test_excludes_expired_grants(self):
        yesterday = datetime.now(pytz.UTC) - timedelta(days=1)
        self._create_grant("10000.00", post=self.post1)
        self._create_grant("40000.00", end_date=yesterday)

        response = self.client.get("/api/grant/available_funding/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["available_funding_in_usd"], 10000.0)

    def test_includes_grants_with_no_end_date(self):
        self._create_grant("25000.00", post=self.post1)

        response = self.client.get("/api/grant/available_funding/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["available_funding_in_usd"], 25000.0)

    def test_includes_grants_with_future_end_date(self):
        tomorrow = datetime.now(pytz.UTC) + timedelta(days=1)
        self._create_grant("15000.00", end_date=tomorrow, post=self.post1)

        response = self.client.get("/api/grant/available_funding/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["available_funding_in_usd"], 15000.0)

    def test_no_active_grants_returns_zero(self):
        response = self.client.get("/api/grant/available_funding/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["available_funding_in_usd"], 0.0)
        self.assertEqual(response.data["available_funding_in_rsc"], 0.0)

    def test_response_is_cached(self):
        self._create_grant("10000.00", post=self.post1)
        self.client.get("/api/grant/available_funding/")

        self._create_grant("90000.00", post=self.post2)
        response = self.client.get("/api/grant/available_funding/")

        self.assertEqual(response.data["available_funding_in_usd"], 10000.0)

    def test_no_auth_required(self):
        self._create_grant("5000.00", post=self.post1)

        self.client.logout()
        response = self.client.get("/api/grant/available_funding/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("available_funding_in_usd", response.data)
        self.assertIn("available_funding_in_rsc", response.data)


class GrantModerationTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod_test", moderator=True)
        self.user = create_random_authenticated_user("regular_test")
        self.author = create_random_authenticated_user("author_test")

        self.post = create_post(created_by=self.author, document_type=GRANT)
        self.grant = Grant.objects.create(
            created_by=self.author,
            unified_document=self.post.unified_document,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="Test Foundation",
            description="Pending grant for testing",
        )

    def test_regular_user_can_create_pending_grant(self):
        # Arrange
        self.client.force_authenticate(self.user)
        post = create_post(created_by=self.user, document_type=GRANT)

        # Act
        response = self.client.post(
            "/api/grant/",
            {
                "unified_document_id": post.unified_document.id,
                "amount": "10000.00",
                "currency": "USD",
                "organization": "User Foundation",
                "description": "User-submitted grant",
            },
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], Grant.PENDING)

    def test_approve_grant(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(f"/api/grant/{self.grant.id}/approve/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.status, Grant.OPEN)
        self.assertTrue(
            Notification.objects.filter(
                notification_type=Notification.GRANT_APPROVED,
                recipient=self.author,
            ).exists()
        )

    def test_decline_grant(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            f"/api/grant/{self.grant.id}/decline/",
            {"reason": "Does not meet guidelines", "reason_choice": "LOW_QUALITY"},
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.status, Grant.DECLINED)
        self.post.unified_document.refresh_from_db()
        self.assertTrue(self.post.unified_document.is_removed)
        self.assertTrue(
            Notification.objects.filter(
                notification_type=Notification.GRANT_DECLINED,
                recipient=self.author,
            ).exists()
        )

        grant_ct = ContentType.objects.get_for_model(Grant)
        flag = Flag.objects.get(
            content_type=grant_ct,
            object_id=self.grant.id,
            created_by=self.moderator,
        )
        self.assertEqual(flag.reason, "Does not meet guidelines")
        self.assertEqual(flag.reason_choice, "LOW_QUALITY")
        self.assertIsNotNone(flag.verdict_created_date)

        verdict = Verdict.objects.get(flag=flag)
        self.assertEqual(verdict.created_by, self.moderator)
        self.assertTrue(verdict.is_content_removed)

    def test_approve_and_decline_reject_non_pending(self):
        # Arrange
        self.grant.status = Grant.OPEN
        self.grant.save()
        self.client.force_authenticate(self.moderator)

        # Act / Assert
        for action in ["approve", "decline"]:
            response = self.client.post(f"/api/grant/{self.grant.id}/{action}/")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_moderation_actions_require_moderator(self):
        # Arrange
        self.client.force_authenticate(self.user)

        # Act / Assert
        for url in [
            f"/api/grant/{self.grant.id}/approve/",
            f"/api/grant/{self.grant.id}/decline/",
        ]:
            response = self.client.post(url)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.get("/api/grant/pending/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_pending_list(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get("/api/grant/pending/")

        # Assert — returns pending grants with post_id
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.grant.id)
        self.assertEqual(results[0]["post_id"], self.post.id)

        # Act — excludes non-pending
        self.grant.status = Grant.OPEN
        self.grant.save()
        response = self.client.get("/api/grant/pending/")

        # Assert
        self.assertEqual(len(response.data["results"]), 0)

    def test_pending_list_filter_by_organization(self):
        # Arrange
        other_post = create_post(created_by=self.author, document_type=GRANT)
        Grant.objects.create(
            created_by=self.author,
            unified_document=other_post.unified_document,
            amount=Decimal("5000.00"),
            currency="USD",
            organization="Unrelated Org",
            description="Decoy grant",
        )
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get("/api/grant/pending/", {"organization": "Test"})

        # Assert
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.grant.id)

    def test_pending_list_filter_by_created_by(self):
        # Arrange
        other_author = create_random_authenticated_user("other_author")
        other_post = create_post(created_by=other_author, document_type=GRANT)
        Grant.objects.create(
            created_by=other_author,
            unified_document=other_post.unified_document,
            amount=Decimal("5000.00"),
            currency="USD",
            description="Other author's grant",
        )
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get(
            "/api/grant/pending/", {"created_by": self.author.id}
        )

        # Assert
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.grant.id)

    def test_approve_invalidates_available_funding_cache(self):
        # Arrange
        cache.set("grant_available_funding", {"stale": True})
        self.client.force_authenticate(self.moderator)

        # Act
        self.client.post(f"/api/grant/{self.grant.id}/approve/")

        # Assert
        self.assertIsNone(cache.get("grant_available_funding"))

    def test_moderator_can_update_grant_they_did_not_create(self):
        # Arrange
        self.grant.status = Grant.OPEN
        self.grant.save()
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.patch(
            f"/api/grant/{self.grant.id}/",
            {"description": "Updated by moderator"},
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.description, "Updated by moderator")

    def test_non_moderator_cannot_update_others_grant(self):
        # Arrange
        self.grant.status = Grant.OPEN
        self.grant.save()
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.patch(
            f"/api/grant/{self.grant.id}/",
            {"description": "Should be denied"},
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class GrantModerationServiceTests(APITestCase):
    """Tests for GrantModerationService branches not reached by API tests (DOI assignment, decline internals)."""

    def setUp(self):
        self.moderator = create_random_authenticated_user("svc_mod", moderator=True)
        self.author = create_random_authenticated_user("svc_author")
        self.service = GrantModerationService()
        self.post = create_post(created_by=self.author, document_type=GRANT)
        self.grant = Grant.objects.create(
            created_by=self.author,
            unified_document=self.post.unified_document,
            amount=Decimal("50000.00"),
            currency="USD",
            description="Test grant",
        )

    @patch("purchase.services.grant_service.DOI")
    def test_approve_assigns_doi_and_notifies(self, mock_doi_class):
        # Arrange
        mock_doi_class.return_value.doi = "10.55277/rhj.test"

        # Act
        self.service.approve_grant(self.grant, self.moderator)

        # Assert
        self.post.refresh_from_db()
        self.assertEqual(self.post.doi, "10.55277/rhj.test")
        mock_doi_class.return_value.register_doi_for_post.assert_called_once()
        self.assertTrue(
            Notification.objects.filter(
                notification_type=Notification.GRANT_APPROVED,
                recipient=self.author,
            ).exists()
        )

    @patch("purchase.services.grant_service.DOI")
    def test_approve_skips_doi_when_already_set(self, mock_doi_class):
        # Arrange
        self.post.doi = "10.55277/existing"
        self.post.save(update_fields=["doi"])

        # Act
        self.service.approve_grant(self.grant, self.moderator)

        # Assert
        mock_doi_class.assert_not_called()

    def test_decline_creates_flag_removes_doc_and_notifies(self):
        # Act
        self.service.decline_grant(
            self.grant, self.moderator, reason="Spam", reason_choice="SPAM"
        )

        # Assert
        grant_ct = ContentType.objects.get_for_model(Grant)
        flag = Flag.objects.get(content_type=grant_ct, object_id=self.grant.id)
        self.assertEqual(flag.reason_choice, "SPAM")
        self.assertTrue(
            Verdict.objects.filter(flag=flag, is_content_removed=True).exists()
        )
        self.post.unified_document.refresh_from_db()
        self.assertTrue(self.post.unified_document.is_removed)
        self.assertTrue(
            Notification.objects.filter(
                notification_type=Notification.GRANT_DECLINED,
                recipient=self.author,
            ).exists()
        )

    @patch("purchase.services.grant_service.DOI")
    def test_approve_skips_doi_when_no_post(self, mock_doi_class):
        # Arrange
        self.post.unified_document.posts.all().delete()

        # Act
        self.service.approve_grant(self.grant, self.moderator)

        # Assert
        mock_doi_class.assert_not_called()

    @patch("purchase.services.grant_service.DOI")
    def test_approve_doi_failure_does_not_block(self, mock_doi_class):
        # Arrange
        mock_doi_class.side_effect = Exception("DOI service unavailable")

        # Act
        self.service.approve_grant(self.grant, self.moderator)

        # Assert
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.status, Grant.OPEN)

    @patch("purchase.services.grant_service.Notification")
    def test_notification_failure_does_not_block_approve(self, mock_notif_cls):
        # Arrange
        mock_notif_cls.objects.create.side_effect = Exception("Notification failed")
        mock_notif_cls.GRANT_APPROVED = Notification.GRANT_APPROVED

        # Act
        self.service.approve_grant(self.grant, self.moderator)

        # Assert
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.status, Grant.OPEN)

    @patch("purchase.services.grant_service.Notification")
    def test_notification_failure_does_not_block_decline(self, mock_notif_cls):
        # Arrange
        mock_notif_cls.objects.create.side_effect = Exception("Notification failed")
        mock_notif_cls.GRANT_DECLINED = Notification.GRANT_DECLINED

        # Act
        self.service.decline_grant(self.grant, self.moderator)

        # Assert
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.status, Grant.DECLINED)

    @patch("purchase.services.grant_service._create_post_feed_entries")
    @patch("purchase.services.grant_service.DOI")
    def test_approve_handles_feed_entry_creation_failure(self, mock_doi, mock_create):
        # Arrange
        mock_doi.return_value.doi = "10.55277/test"
        mock_create.side_effect = Exception("Feed entry creation failed")

        # Act
        self.service.approve_grant(self.grant, self.moderator)

        # Assert
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.status, Grant.OPEN)
