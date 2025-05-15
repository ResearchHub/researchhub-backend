from allauth.account.models import EmailAddress, EmailConfirmation
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITransactionTestCase

User = get_user_model()


class CustomVerifyEmailViewTest(APITransactionTestCase):
    reset_sequences = False

    def setUp(self):
        self.user = User.objects.create(
            username="testuser@example.com",
            email="testuser@example.com",
            password="testpassword123",
            first_name="Test",
            last_name="User",
        )

        self.email_address = EmailAddress.objects.create(
            user=self.user, email=self.user.email, primary=True, verified=False
        )

        self.confirmation = EmailConfirmation.create(self.email_address)
        self.confirmation.sent = timezone.now()
        self.confirmation.save()
        self.key = self.confirmation.key

        self.verify_url = "/api/auth/register/verify-email/"

    def test_email_verification_success(self):
        """
        Test successful email verification with token in response.
        """
        response = self.client.post(self.verify_url, {"key": self.key}, format="json")

        self.assertEqual(response.status_code, 200)

        data = response.data

        self.assertIn("detail", data)
        self.assertEqual(data["detail"], "ok")

        self.assertIn("key", data)  # Should have token key

        self.assertIn("user", data)
        self.assertEqual(data["user"]["id"], self.user.id)

        token = Token.objects.get(key=data["key"])
        self.assertEqual(token.user.id, self.user.id)

        email_address = EmailAddress.objects.get(user=self.user)
        self.assertTrue(email_address.verified)

    def test_email_verification_invalid_key(self):
        """
        Test email verification with invalid key.
        """
        user2 = User.objects.create(
            username="testuser2@example.com",
            email="testuser2@example.com",
            password="testpassword123",
            first_name="Test2",
            last_name="User2",
        )

        email_address2 = EmailAddress.objects.create(
            user=user2, email=user2.email, primary=True, verified=False
        )

        response = self.client.post(
            self.verify_url, {"key": "invalid-key"}, format="json"
        )

        self.assertEqual(response.status_code, 404)

        email_address2.refresh_from_db()
        self.assertFalse(email_address2.verified)

    def test_email_verification_missing_key(self):
        """
        Test email verification without a key.
        """
        user3 = User.objects.create(
            username="testuser3@example.com",
            email="testuser3@example.com",
            password="testpassword123",
            first_name="Test3",
            last_name="User3",
        )

        email_address3 = EmailAddress.objects.create(
            user=user3, email=user3.email, primary=True, verified=False
        )

        response = self.client.post(self.verify_url, {}, format="json")

        self.assertEqual(response.status_code, 400)

        email_address3.refresh_from_db()
        self.assertFalse(email_address3.verified)
