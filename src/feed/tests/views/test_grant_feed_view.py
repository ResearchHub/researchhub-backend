from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from purchase.models import Grant, GrantApplication
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user


class GrantFeedViewTests(APITestCase):
    def setUp(self):
        # Clear any existing data to avoid test interference
        cache.clear()  # Clear cache to avoid test interference
        GrantApplication.objects.all().delete()
        Grant.objects.all().delete()
        ResearchhubPost.objects.filter(document_type=GRANT).delete()
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

    def tearDown(self):
        """Clean up after each test"""
        GrantApplication.objects.all().delete()
        Grant.objects.all().delete()
        ResearchhubPost.objects.filter(document_type=GRANT).delete()
        cache.clear()  # Clear cache to avoid test interference

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
        response = self.client.get("/api/grant_feed/?status=OPEN")

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

        # Check grant-specific fields are in the content_object.grant
        content_object = result["content_object"]
        self.assertIn("grant", content_object)
        grant_data = content_object["grant"]
        self.assertIn("organization", grant_data)
        self.assertIn("amount", grant_data)
        self.assertIn("is_expired", grant_data)

    def test_grant_feed_organization_field(self):
        """Test that the organization field is correctly populated"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?status=OPEN")

        result = response.data["results"][0]
        grant_data = result["content_object"]["grant"]
        self.assertEqual(grant_data["organization"], "NSF")

    def test_grant_feed_grant_amount_field(self):
        """Test that the grant_amount field is correctly populated"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?status=OPEN")

        result = response.data["results"][0]
        grant_amount = result["content_object"]["grant"]["amount"]

        self.assertEqual(grant_amount["usd"], 50000.0)
        self.assertEqual(grant_amount["formatted"], "50,000.00 USD")

    def test_grant_feed_is_expired_field(self):
        """Test that the is_expired field is correctly populated"""
        self.client.force_authenticate(self.user)

        # Test open grant (not expired)
        response = self.client.get("/api/grant_feed/?status=OPEN")
        result = response.data["results"][0]
        grant_data = result["content_object"]["grant"]
        self.assertFalse(grant_data["is_expired"])

        # Test closed grant (expired)
        response = self.client.get("/api/grant_feed/?status=CLOSED")
        result = response.data["results"][0]
        grant_data = result["content_object"]["grant"]
        self.assertTrue(grant_data["is_expired"])

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

    def test_grant_feed_includes_applications(self):
        """Test that grant feed includes application data"""

        # Create applicant users
        applicant1 = create_random_authenticated_user("applicant1")
        applicant2 = create_random_authenticated_user("applicant2")

        # Create preregistration posts for applications
        preregistration1 = create_post(
            created_by=applicant1,
            document_type=PREREGISTRATION,
            title="Preregistration 1",
        )
        preregistration2 = create_post(
            created_by=applicant2,
            document_type=PREREGISTRATION,
            title="Preregistration 2",
        )

        # Create applications
        GrantApplication.objects.create(
            grant=self.open_grant,
            preregistration_post=preregistration1,
            applicant=applicant1,
        )
        GrantApplication.objects.create(
            grant=self.open_grant,
            preregistration_post=preregistration2,
            applicant=applicant2,
        )

        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/")

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertTrue(len(results) > 0)

        # Find the grant entry
        grant_entry = None
        for entry in results:
            if entry["content_object"]["id"] == self.open_post.id:
                grant_entry = entry
                break

        self.assertIsNotNone(grant_entry)
        grant_data = grant_entry["content_object"]["grant"]
        self.assertIn("applications", grant_data)

        applications = grant_data["applications"]
        self.assertEqual(len(applications), 2)

        # Check application structure
        application1 = applications[0]
        self.assertIn("id", application1)
        self.assertIn("created_date", application1)
        self.assertIn("applicant", application1)
        self.assertIn("preregistration_post_id", application1)

        # Check applicant structure using SimpleAuthorSerializer
        applicant_data = application1["applicant"]
        self.assertIn("id", applicant_data)
        self.assertIn("first_name", applicant_data)
        self.assertIn("last_name", applicant_data)
        self.assertIn("profile_image", applicant_data)
        self.assertIn("headline", applicant_data)
        self.assertIn("user", applicant_data)

        # Verify applicant IDs are correct
        applicant_ids = [app["applicant"]["id"] for app in applications]
        self.assertIn(applicant1.author_profile.id, applicant_ids)
        self.assertIn(applicant2.author_profile.id, applicant_ids)

    def test_grant_feed_empty_applications(self):
        """Test that grant feed handles grants with no applications"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/")

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertTrue(len(results) > 0)

        # Find the grant entry
        grant_entry = None
        for entry in results:
            if entry["content_object"]["id"] == self.open_post.id:
                grant_entry = entry
                break

        self.assertIsNotNone(grant_entry)
        grant_data = grant_entry["content_object"]["grant"]
        self.assertIn("applications", grant_data)

        # Should be empty list when no applications
        applications = grant_data["applications"]
        self.assertEqual(len(applications), 0)
        self.assertIsInstance(applications, list)

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
        grant_data = result["content_object"]["grant"]
        self.assertEqual(grant_data["organization"], "NSF")

    def test_grant_feed_no_grants(self):
        """Test grant feed when no grants match the filter"""
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?organization=NONEXISTENT")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 0)

    def test_grant_feed_order_by_newest(self):
        """Test grant feed ordering by newest"""
        new_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        _ = ResearchhubPost.objects.create(
            title="Newest Grant",
            created_by=self.user,
            document_type=GRANT,
            unified_document=new_doc,
        )
        # Create grants with different statuses
        _ = Grant.objects.create(
            created_by=self.moderator,
            unified_document=new_doc,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="NSF",
            description="Open research grant",
            status=Grant.OPEN,
            end_date=datetime.now(pytz.UTC) + timedelta(days=30),
        )

        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?ordering=newest")

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]

        # First result should be the most recently created grant
        first_result = results[0]
        self.assertEqual(first_result["content_object"]["title"], "Newest Grant")

    def test_grant_feed_order_by_amount(self):
        """Test grant feed ordering by grant amount"""
        largest_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        _ = ResearchhubPost.objects.create(
            title="Largest Open Grant",
            created_by=self.user,
            document_type=GRANT,
            unified_document=largest_doc,
        )
        # Create grants with different statuses
        _ = Grant.objects.create(
            created_by=self.moderator,
            unified_document=largest_doc,
            amount=Decimal("90000.00"),
            currency="USD",
            organization="NSF",
            description="Open research grant",
            status=Grant.OPEN,
            end_date=datetime.now(pytz.UTC) + timedelta(days=30),
        )

        medium_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        _ = ResearchhubPost.objects.create(
            title="Medium Open Grant",
            created_by=self.user,
            document_type=GRANT,
            unified_document=medium_doc,
        )
        # Create grants with different statuses
        _ = Grant.objects.create(
            created_by=self.moderator,
            unified_document=medium_doc,
            amount=Decimal("70000.00"),
            currency="USD",
            organization="NSF",
            description="Open research grant",
            status=Grant.OPEN,
            end_date=datetime.now(pytz.UTC) + timedelta(days=30),
        )

        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?ordering=grants__amount")

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]

        # First result should be the grant with the highest amount
        first_result = results[0]
        self.assertEqual(
            first_result["content_object"]["grant"]["amount"]["usd"], 90000.0
        )

        second_result = results[1]
        self.assertEqual(
            second_result["content_object"]["grant"]["amount"]["usd"], 70000.0
        )

    def test_grant_feed_order_by_end_date(self):
        """Test grant feed ordering by grant end date (soonest first)"""
        soonest_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        _ = ResearchhubPost.objects.create(
            title="Soonest Ending Grant",
            created_by=self.user,
            document_type=GRANT,
            unified_document=soonest_doc,
        )

        _ = Grant.objects.create(
            created_by=self.moderator,
            unified_document=soonest_doc,
            amount=Decimal("60000.00"),
            currency="USD",
            organization="NSF",
            description="Open research grant",
            status=Grant.OPEN,
            end_date=datetime.now(pytz.UTC) + timedelta(days=10),
        )

        later_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        _ = ResearchhubPost.objects.create(
            title="Later Ending Grant",
            created_by=self.user,
            document_type=GRANT,
            unified_document=later_doc,
        )

        _ = Grant.objects.create(
            created_by=self.moderator,
            unified_document=later_doc,
            amount=Decimal("60000.00"),
            currency="USD",
            organization="NSF",
            description="Open research grant",
            status=Grant.OPEN,
            end_date=datetime.now(pytz.UTC) + timedelta(days=20),
        )

        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?ordering=end_date")

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]

        # First result should be the grant with the soonest end date
        first_result = results[0]
        self.assertEqual(
            first_result["content_object"]["title"], "Soonest Ending Grant"
        )

        second_result = results[1]
        self.assertEqual(second_result["content_object"]["title"], "Later Ending Grant")

    def test_grant_feed_order_by_application_count(self):
        """Test grant feed ordering by number of applications (most first)"""
        # Create applicant users
        applicant1 = create_random_authenticated_user("applicant1")
        applicant2 = create_random_authenticated_user("applicant2")
        applicant3 = create_random_authenticated_user("applicant3")

        # Create preregistration posts for applications
        preregistration1 = create_post(
            created_by=applicant1,
            document_type=PREREGISTRATION,
            title="Preregistration 1",
        )
        preregistration2 = create_post(
            created_by=applicant2,
            document_type=PREREGISTRATION,
            title="Preregistration 2",
        )
        preregistration3 = create_post(
            created_by=applicant3,
            document_type=PREREGISTRATION,
            title="Preregistration 3",
        )

        # Create additional grants
        grant1_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        grant1_post = ResearchhubPost.objects.create(
            title="Grant with 2 Applications",
            created_by=self.user,
            document_type=GRANT,
            unified_document=grant1_doc,
        )
        grant1 = Grant.objects.create(
            created_by=self.moderator,
            unified_document=grant1_post.unified_document,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="NSF",
            description="Research grant 1",
            status=Grant.OPEN,
            end_date=datetime.now(pytz.UTC) + timedelta(days=30),
        )

        grant2_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        grant2_post = ResearchhubPost.objects.create(
            title="Grant with 1 Application",
            created_by=self.user,
            document_type=GRANT,
            unified_document=grant2_doc,
        )
        grant2 = Grant.objects.create(
            created_by=self.moderator,
            unified_document=grant2_post.unified_document,
            amount=Decimal("60000.00"),
            currency="USD",
            organization="NIH",
            description="Research grant 2",
            status=Grant.OPEN,
            end_date=datetime.now(pytz.UTC) + timedelta(days=40),
        )

        # Create applications
        GrantApplication.objects.create(
            grant=grant1, preregistration_post=preregistration1, applicant=applicant1
        )

        GrantApplication.objects.create(
            grant=grant1, preregistration_post=preregistration2, applicant=applicant2
        )

        GrantApplication.objects.create(
            grant=grant2, preregistration_post=preregistration3, applicant=applicant3
        )

        self.client.force_authenticate(self.user)
        response = self.client.get("/api/grant_feed/?ordering=application_count")

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]

        # First result should be the grant with the soonest end date
        first_result = results[0]
        self.assertEqual(
            first_result["content_object"]["title"], "Grant with 2 Applications"
        )

        second_result = results[1]
        self.assertEqual(
            second_result["content_object"]["title"], "Grant with 1 Application"
        )
