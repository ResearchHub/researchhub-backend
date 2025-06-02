from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase

from purchase.models import Grant, GrantApplication
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.tests.helpers import create_random_authenticated_user


class GrantApplicationModelTests(TestCase):
    def setUp(self):
        """Set up test data"""
        self.user = create_random_authenticated_user("test_user")
        self.grant_creator = create_random_authenticated_user(
            "grant_creator", moderator=True
        )

        # Create a grant post and grant
        self.grant_post = create_post(
            created_by=self.grant_creator, document_type=GRANT
        )
        self.grant = Grant.objects.create(
            created_by=self.grant_creator,
            unified_document=self.grant_post.unified_document,
            amount=Decimal("10000.00"),
            currency="USD",
            organization="Test Foundation",
            description="Test grant for research",
            status=Grant.OPEN,
        )

        # Create a preregistration post
        self.preregistration_post = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Test Preregistration",
        )

    def test_create_grant_application(self):
        """Test creating a grant application"""
        application = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.preregistration_post,
            applicant=self.user,
        )

        self.assertEqual(application.grant, self.grant)
        self.assertEqual(application.preregistration_post, self.preregistration_post)
        self.assertEqual(application.applicant, self.user)
        self.assertIsNotNone(application.created_date)
        self.assertIsNotNone(application.updated_date)

    def test_grant_application_string_representation(self):
        """Test the string representation of GrantApplication"""
        application = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.preregistration_post,
            applicant=self.user,
        )

        expected_str = f"Grant Application: {self.grant} - {self.preregistration_post}"
        self.assertEqual(str(application), expected_str)

    def test_unique_constraint_prevents_duplicate_applications(self):
        """Test that the unique constraint prevents duplicate applications"""
        # Create first application
        GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.preregistration_post,
            applicant=self.user,
        )

        # Attempt to create duplicate application should raise IntegrityError
        with self.assertRaises(IntegrityError):
            GrantApplication.objects.create(
                grant=self.grant,
                preregistration_post=self.preregistration_post,
                applicant=self.user,
            )

    def test_different_applicants_can_apply_to_same_grant_with_different_posts(self):
        """Test that different users can apply to the same grant with different posts"""
        user2 = create_random_authenticated_user("user2")
        preregistration_post2 = create_post(
            created_by=user2,
            document_type=PREREGISTRATION,
            title="Second Preregistration",
        )

        # First application
        application1 = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.preregistration_post,
            applicant=self.user,
        )

        # Second application with different user and post
        application2 = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=preregistration_post2,
            applicant=user2,
        )

        self.assertNotEqual(application1.applicant, application2.applicant)
        self.assertNotEqual(
            application1.preregistration_post, application2.preregistration_post
        )
        self.assertEqual(application1.grant, application2.grant)

    def test_same_post_can_apply_to_different_grants(self):
        """Test that the same post can apply to different grants"""
        # Create a second grant
        grant_post2 = create_post(created_by=self.grant_creator, document_type=GRANT)
        grant2 = Grant.objects.create(
            created_by=self.grant_creator,
            unified_document=grant_post2.unified_document,
            amount=Decimal("15000.00"),
            currency="USD",
            organization="Another Foundation",
            description="Another test grant",
            status=Grant.OPEN,
        )

        # Apply same post to both grants
        application1 = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.preregistration_post,
            applicant=self.user,
        )

        application2 = GrantApplication.objects.create(
            grant=grant2,
            preregistration_post=self.preregistration_post,
            applicant=self.user,
        )

        self.assertNotEqual(application1.grant, application2.grant)
        self.assertEqual(
            application1.preregistration_post, application2.preregistration_post
        )
        self.assertEqual(application1.applicant, application2.applicant)

    def test_related_name_applications_on_grant(self):
        """Test that grants can access their applications via related name"""
        application = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.preregistration_post,
            applicant=self.user,
        )

        applications = self.grant.applications.all()
        self.assertEqual(applications.count(), 1)
        self.assertEqual(applications.first(), application)

    def test_related_name_grant_applications_on_post(self):
        """Test that posts can access their grant applications via related name"""
        application = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.preregistration_post,
            applicant=self.user,
        )

        applications = self.preregistration_post.grant_applications.all()
        self.assertEqual(applications.count(), 1)
        self.assertEqual(applications.first(), application)

    def test_related_name_grant_applications_on_user(self):
        """Test that users can access their grant applications via related name"""
        application = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.preregistration_post,
            applicant=self.user,
        )

        applications = self.user.grant_applications.all()
        self.assertEqual(applications.count(), 1)
        self.assertEqual(applications.first(), application)

    def test_cascade_delete_grant(self):
        """Test that deleting a grant cascades to delete applications"""
        application = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.preregistration_post,
            applicant=self.user,
        )

        application_id = application.id
        self.grant.delete()

        # Application should be deleted
        self.assertFalse(GrantApplication.objects.filter(id=application_id).exists())

    def test_cascade_delete_post(self):
        """Test that deleting a post cascades to delete applications"""
        application = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.preregistration_post,
            applicant=self.user,
        )

        application_id = application.id
        self.preregistration_post.delete()

        # Application should be deleted
        self.assertFalse(GrantApplication.objects.filter(id=application_id).exists())

    def test_cascade_delete_user(self):
        """Test that deleting a user cascades to delete applications"""
        application = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.preregistration_post,
            applicant=self.user,
        )

        application_id = application.id
        self.user.delete()

        # Application should be deleted
        self.assertFalse(GrantApplication.objects.filter(id=application_id).exists())
