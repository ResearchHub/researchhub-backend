from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from purchase.models import Grant, GrantApplication
from purchase.related_models.grant_application_model import GrantApplicationStatus
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.tests.helpers import create_random_authenticated_user


class GrantApplicationViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user(
            "app_moderator", moderator=True
        )
        self.regular_user = create_random_authenticated_user("app_user")
        self.applicant = create_random_authenticated_user("applicant")

        self.grant_post = create_post(created_by=self.moderator, document_type=GRANT)

        # Create a grant
        self.grant = Grant.objects.create(
            created_by=self.moderator,
            unified_document=self.grant_post.unified_document,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="Test Foundation",
            description="Test grant for application testing",
            status=Grant.OPEN,
        )

        # Create a preregistration post
        self.preregistration_post = create_post(
            created_by=self.applicant,
            document_type=PREREGISTRATION,
            title="Test Preregistration",
        )

        # Create a grant application
        self.application = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.preregistration_post,
            applicant=self.applicant,
            status=GrantApplicationStatus.PENDING,
        )

    def test_list_applications_for_grant_authenticated(self):
        """Test that authenticated users can list grant applications for a grant"""
        # Arrange
        self.client.force_authenticate(self.regular_user)

        # Act
        response = self.client.get(f"/api/grant/{self.grant.id}/applications/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        application_data = response.data[0]
        self.assertEqual(application_data["id"], self.application.id)
        self.assertEqual(application_data["status"], GrantApplicationStatus.PENDING)
        self.assertIn("applicant", application_data)
        self.assertIn("preregistration_post_id", application_data)
        self.assertIn("grant_id", application_data)

    def test_list_applications_unauthenticated(self):
        """Test that unauthenticated users cannot list grant applications"""
        # Act
        response = self.client.get(f"/api/grant/{self.grant.id}/applications/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_update_application_status_moderator_success(self):
        """Test that moderators can successfully update application status"""
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        data = {"status": GrantApplicationStatus.APPROVED}
        url = f"/api/grant/{self.grant.id}/applications/{self.application.id}/status/"
        response = self.client.put(url, data)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)
        self.assertIn("application", response.data)
        self.assertEqual(
            response.data["application"]["status"], GrantApplicationStatus.APPROVED
        )

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, GrantApplicationStatus.APPROVED)

    def test_update_application_status_post_method(self):
        """Test that the status endpoint accepts POST requests too"""
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        data = {"status": GrantApplicationStatus.REJECTED}
        url = f"/api/grant/{self.grant.id}/applications/{self.application.id}/status/"
        response = self.client.post(url, data)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["application"]["status"], GrantApplicationStatus.REJECTED
        )

    def test_update_application_status_regular_user_forbidden(self):
        """Test that regular users cannot update application status"""
        # Arrange
        self.client.force_authenticate(self.regular_user)

        # Act
        data = {"status": GrantApplicationStatus.APPROVED}
        url = f"/api/grant/{self.grant.id}/applications/{self.application.id}/status/"
        response = self.client.put(url, data)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_application_status_applicant_forbidden(self):
        """Test that even the applicant cannot update their own application status"""
        # Arrange
        self.client.force_authenticate(self.applicant)

        # Act
        data = {"status": GrantApplicationStatus.APPROVED}
        url = f"/api/grant/{self.grant.id}/applications/{self.application.id}/status/"
        response = self.client.put(url, data)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_application_status_unauthenticated(self):
        """Test that unauthenticated users cannot update application status"""
        # Arrange
        data = {"status": GrantApplicationStatus.APPROVED}

        # Act
        url = f"/api/grant/{self.grant.id}/applications/{self.application.id}/status/"
        response = self.client.put(url, data)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_update_application_status_invalid_status(self):
        """Test that invalid status values are rejected"""
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        data = {"status": "INVALID_STATUS"}
        url = f"/api/grant/{self.grant.id}/applications/{self.application.id}/status/"
        response = self.client.put(url, data)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", response.data)

    def test_update_application_status_missing_status(self):
        """Test that missing status field is handled properly"""
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        data = {}
        url = f"/api/grant/{self.grant.id}/application/{self.application.id}/status/"
        response = self.client.put(url, data)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_application_status_nonexistent_grant(self):
        """Test that updating status with non-existent grant returns 404"""
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        data = {"status": GrantApplicationStatus.APPROVED}
        url = f"/api/grant/99999/applications/{self.application.id}/status/"
        response = self.client.put(url, data)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("Grant not found", response.data["error"])

    def test_update_application_status_nonexistent_application(self):
        """Test that updating status of non-existent application returns 404"""
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        data = {"status": GrantApplicationStatus.APPROVED}
        url = f"/api/grant/{self.grant.id}/applications/99999/status/"
        response = self.client.put(url, data)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("Application not found for this grant", response.data["error"])

    def test_update_application_status_wrong_grant(self):
        """Test that updating application status with wrong grant ID returns 404"""
        # Arrange
        other_grant_post = create_post(created_by=self.moderator, document_type=GRANT)
        other_grant = Grant.objects.create(
            created_by=self.moderator,
            unified_document=other_grant_post.unified_document,
            amount=Decimal("25000.00"),
            currency="USD",
            organization="Other Foundation",
            description="Other grant",
            status=Grant.OPEN,
        )

        # Act
        self.client.force_authenticate(self.moderator)
        data = {"status": GrantApplicationStatus.APPROVED}
        # Try to update application using wrong grant ID
        url = f"/api/grant/{other_grant.id}/applications/{self.application.id}/status/"
        response = self.client.put(url, data)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("Application not found for this grant", response.data["error"])

    def test_application_serializer_includes_related_data(self):
        """Test that the application serializer includes related data"""
        # Arrange
        self.client.force_authenticate(self.regular_user)

        # Act
        response = self.client.get(f"/api/grant/{self.grant.id}/applications/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        application_data = response.data[0]
        self.assertIn("applicant", application_data)
        applicant_data = application_data["applicant"]
        self.assertIn("id", applicant_data)
        self.assertIn("first_name", applicant_data)
        self.assertIn("last_name", applicant_data)
        self.assertEqual(
            application_data["preregistration_post_id"], self.preregistration_post.id
        )
        self.assertEqual(application_data["grant_id"], self.grant.id)

    def test_update_status_from_approved_to_rejected(self):
        """Test updating status from approved to rejected works"""
        # Arrange
        self.application.status = GrantApplicationStatus.APPROVED
        self.application.save()
        self.client.force_authenticate(self.moderator)
        data = {"status": GrantApplicationStatus.REJECTED}

        # Act
        url = f"/api/grant/{self.grant.id}/applications/{self.application.id}/status/"
        response = self.client.put(url, data)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, GrantApplicationStatus.REJECTED)

    def test_update_status_message_shows_transition(self):
        """Test that the response message shows the status transition"""
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        data = {"status": GrantApplicationStatus.APPROVED}
        url = f"/api/grant/{self.grant.id}/applications/{self.application.id}/status/"
        response = self.client.put(url, data)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected_message = (
            f"Application status updated from {GrantApplicationStatus.PENDING} "
            f"to {GrantApplicationStatus.APPROVED}"
        )
        self.assertEqual(response.data["message"], expected_message)

    def test_multiple_applications_for_grant(self):
        """Test listing multiple applications for a grant"""
        # Arrange
        applicant2 = create_random_authenticated_user("applicant2")
        preregistration_post2 = create_post(
            created_by=applicant2,
            document_type=PREREGISTRATION,
            title="Second Preregistration",
        )
        application2 = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=preregistration_post2,
            applicant=applicant2,
            status=GrantApplicationStatus.APPROVED,
        )
        self.client.force_authenticate(self.regular_user)

        # Act
        response = self.client.get(f"/api/grant/{self.grant.id}/applications/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

        # check that both applications are returned
        application_ids = [app["id"] for app in response.data]
        self.assertIn(self.application.id, application_ids)
        self.assertIn(application2.id, application_ids)
