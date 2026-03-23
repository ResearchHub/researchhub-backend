from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.contrib.auth import get_user_model
from rest_framework.test import APITransactionTestCase

User = get_user_model()


class UpdateEmailTest(APITransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="user@researchhub.com",
            email="user@researchhub.com",
            password="testpass123",
        )
        EmailAddress.objects.create(
            user=self.user,
            email=self.user.email,
            primary=True,
            verified=True,
        )
        self.url = "/api/user/update_email/"

    def test_update_email(self):
        """
        Test the happy path of an email address change.
        """
        # Arrange
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.post(
            self.url, {"email": "new@researchhub.com"}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertIn("Verification email sent", response.data["detail"])

        pending = EmailAddress.objects.get(user=self.user, email="new@researchhub.com")
        self.assertFalse(pending.verified)
        self.assertFalse(pending.primary)

    def test_update_email_with_same_email(self):
        """
        Update with the same email should fail with HTTP 400.
        """
        # Arrange
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.post(
            self.url, {"email": "user@researchhub.com"}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 400)

    def test_update_email_empty_email(self):
        """
        Update without new email should fail with HTTP 400.
        """
        # Arrange
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.post(self.url, {"email": ""}, format="json")

        # Assert
        self.assertEqual(response.status_code, 400)

    def test_update_email_change_conflict(self):
        """
        Update with an email that is already in use should fail with HTTP 409.
        """
        # Arrange
        User.objects.create_user(
            username="other@researchhub.com",
            email="other@researchhub.com",
            password="testpass123",
        )
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.post(
            self.url, {"email": "other@researchhub.com"}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 409)

    def test_update_email_unauthenticated(self):
        """
        Unauthenticated users should not be able to request an email change.
        """
        # Act
        response = self.client.post(
            self.url, {"email": "new@researchhub.com"}, format="json"
        )

        # Assert
        self.assertIn(response.status_code, [401, 403])


class VerifyEmailUpdateTest(APITransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="user@researchhub.com",
            email="user@researchhub.com",
            password="testpass123",
        )
        self.primary = EmailAddress.objects.create(
            user=self.user,
            email=self.user.email,
            primary=True,
            verified=True,
        )
        self.verify_url = "/api/auth/register/verify-email/"

    def test_verify_email_change_swaps_email(self):
        """
        Test that verifying an email change swaps the user's email and username.
        """
        # Arrange
        new_address = EmailAddress.objects.create(
            user=self.user,
            email="new@researchhub.com",
            verified=False,
            primary=False,
        )
        confirmation = EmailConfirmationHMAC(new_address)

        # Act
        response = self.client.post(
            self.verify_url, {"key": confirmation.key}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.get("email_changed"))

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@researchhub.com")
        self.assertEqual(self.user.username, "new@researchhub.com")

        self.assertFalse(
            EmailAddress.objects.filter(email="user@researchhub.com").exists()
        )
