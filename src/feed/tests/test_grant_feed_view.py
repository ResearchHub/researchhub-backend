from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.test import TestCase
from rest_framework.test import APITestCase

from purchase.models import Grant
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from user.tests.helpers import create_random_authenticated_user


class GrantFeedViewTests(APITestCase):
    def setUp(self):
        # Create users
        self.moderator = create_random_authenticated_user(
            "grant_feed_moderator", moderator=True
        )
        self.user = create_random_authenticated_user("grant_feed_user")

        # Create grant posts
        self.open_post = create_post(
            created_by=self.moderator, document_type=GRANT, title="Open Grant"
        )
        self.closed_post = create_post(
            created_by=self.moderator, document_type=GRANT, title="Closed Grant"
        )
        self.completed_post = create_post(
            created_by=self.moderator, document_type=GRANT, title="Completed Grant"
        )

        # Create grants with different statuses
        self.open_grant = Grant.objects.create(
            created_by=self.moderator,
            unified_document=self.open_post.unified_document,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="NSF",
            description="Open research grant",
            status=Grant.OPEN,
            end_date=datetime.now(pytz.UTC) + timedelta(days=30),
        )

        self.closed_grant = Grant.objects.create(
            created_by=self.moderator,
            unified_document=self.closed_post.unified_document,
            amount=Decimal("75000.00"),
            currency="USD",
            organization="NIH",
            description="Closed research grant",
            status=Grant.CLOSED,
            end_date=datetime.now(pytz.UTC) - timedelta(days=10),
        )

        self.completed_grant = Grant.objects.create(
            created_by=self.moderator,
            unified_document=self.completed_post.unified_document,
            amount=Decimal("100000.00"),
            currency="USD",
            organization="DOE",
            description="Completed research grant",
            status=Grant.COMPLETED,
            end_date=datetime.now(pytz.UTC) - timedelta(days=5),
        )

    def test_grant_feed_list_authenticated(self):
        """Test that authenticated users can access the grant feed"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 3)

    def test_grant_feed_list_unauthenticated(self):
        """Test that unauthenticated users can access the grant feed (public access)"""
        response = self.client.get("/api/grant_feed/")
        self.assertEqual(response.status_code, 200)

    def test_grant_feed_filter_by_status_open(self):
        """Test filtering grant feed by OPEN status"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?status=OPEN")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

        result = response.data["results"][0]
        self.assertEqual(result["content_object"]["title"], "Open Grant")

    def test_grant_feed_filter_by_status_closed(self):
        """Test filtering grant feed by CLOSED status"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?status=CLOSED")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

        result = response.data["results"][0]
        self.assertEqual(result["content_object"]["title"], "Closed Grant")

    def test_grant_feed_filter_by_status_completed(self):
        """Test filtering grant feed by COMPLETED status"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?status=COMPLETED")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

        result = response.data["results"][0]
        self.assertEqual(result["content_object"]["title"], "Completed Grant")

    def test_grant_feed_filter_by_organization(self):
        """Test filtering grant feed by organization"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?organization=NSF")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

        result = response.data["results"][0]
        self.assertEqual(result["content_object"]["title"], "Open Grant")

    def test_grant_feed_filter_by_organization_partial_match(self):
        """Test filtering grant feed by partial organization name"""
        self.client.force_authenticate(self.user)
        response = self.client.get(
            "/api/grant_feed/?organization=NI"
        )  # Should match NIH

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

        result = response.data["results"][0]
        self.assertEqual(result["content_object"]["title"], "Closed Grant")

    def test_grant_feed_order_open_first(self):
        """Test that grant feed orders OPEN grants first"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/")

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]

        # First result should be the OPEN grant
        first_result = results[0]
        self.assertEqual(first_result["content_object"]["title"], "Open Grant")

    def test_grant_feed_entry_serializer_fields(self):
        """Test that grant feed entries include the expected fields"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/")

        self.assertEqual(response.status_code, 200)
        result = response.data["results"][0]

        # Check base feed entry fields
        self.assertIn("id", result)
        self.assertIn("content_type", result)
        self.assertIn("content_object", result)
        self.assertIn("created_date", result)
        self.assertIn("action_date", result)
        self.assertIn("action", result)
        self.assertIn("author", result)

        # Check grant-specific fields
        self.assertIn("organization", result)
        self.assertIn("grant_amount", result)
        self.assertIn("is_expired", result)

    def test_grant_feed_organization_field(self):
        """Test that the organization field is correctly populated"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?status=OPEN")

        result = response.data["results"][0]
        self.assertEqual(result["organization"], "NSF")

    def test_grant_feed_grant_amount_field(self):
        """Test that the grant_amount field is correctly populated"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?status=OPEN")

        result = response.data["results"][0]
        grant_amount = result["grant_amount"]

        self.assertEqual(grant_amount["amount"], 50000.0)
        self.assertEqual(grant_amount["currency"], "USD")
        self.assertEqual(grant_amount["formatted"], "50000.00 USD")

    def test_grant_feed_is_expired_field(self):
        """Test that the is_expired field is correctly populated"""
        self.client.force_authenticate(self.user)

        # Test open grant (not expired)
        response = self.client.get("/api/grant_feed/?status=OPEN")
        result = response.data["results"][0]
        self.assertFalse(result["is_expired"])

        # Test closed grant (expired)
        response = self.client.get("/api/grant_feed/?status=CLOSED")
        result = response.data["results"][0]
        self.assertTrue(result["is_expired"])

    def test_grant_feed_content_object_includes_grant_data(self):
        """Test that the content object includes grant-specific data"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?status=OPEN")

        result = response.data["results"][0]
        content_object = result["content_object"]

        # Check that grant data is included
        self.assertIn("grant", content_object)
        grant_data = content_object["grant"]

        self.assertEqual(grant_data["organization"], "NSF")
        self.assertEqual(grant_data["amount"]["usd"], 50000.0)
        self.assertEqual(grant_data["status"], "OPEN")

    def test_grant_feed_pagination(self):
        """Test that grant feed supports pagination"""
        # Create more grants to test pagination
        for i in range(10):
            post = create_post(
                created_by=self.moderator, document_type=GRANT, title=f"Grant {i}"
            )
            Grant.objects.create(
                created_by=self.moderator,
                unified_document=post.unified_document,
                amount=Decimal("10000.00"),
                currency="USD",
                organization=f"Org {i}",
                description=f"Grant {i} description",
                status=Grant.OPEN,
            )

        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("count", response.data)
        self.assertIn("next", response.data)
        self.assertIn("previous", response.data)
        self.assertIn("results", response.data)

    def test_grant_feed_caching(self):
        """Test that grant feed responses can be cached for early pages"""
        self.client.force_authenticate(self.user)

        # First request should populate cache
        response1 = self.client.get("/api/grant_feed/?page=1")
        self.assertEqual(response1.status_code, 200)

        # Second request should potentially use cache
        response2 = self.client.get("/api/grant_feed/?page=1")
        self.assertEqual(response2.status_code, 200)

        # Responses should be identical
        self.assertEqual(response1.data, response2.data)

    def test_grant_feed_invalid_status_filter(self):
        """Test grant feed with invalid status filter"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?status=INVALID")

        # Should return 200 but with no results (invalid status filter is ignored)
        self.assertEqual(response.status_code, 200)

    def test_grant_feed_multiple_filters(self):
        """Test grant feed with multiple filters combined"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?status=OPEN&organization=NSF")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

        result = response.data["results"][0]
        self.assertEqual(result["content_object"]["title"], "Open Grant")
        self.assertEqual(result["organization"], "NSF")

    def test_grant_feed_no_grants(self):
        """Test grant feed when no grants match the filter"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?organization=NONEXISTENT")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 0)
