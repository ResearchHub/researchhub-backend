from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from referral.models import ReferralSignup
from user.tests.helpers import create_random_default_user

User = get_user_model()


class ReferralRegistrationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.referrer = create_random_default_user("referrer")
        self.referrer_code = self.referrer.referral_code

    def test_user_registration_with_referral_code_does_not_create_signup(self):
        """Test that registering with a valid referral code no longer creates ReferralSignup"""
        registration_data = {
            "email": "newuser@example.com",
            "password1": "testpassword123!",
            "password2": "testpassword123!",
            "first_name": "Test",
            "last_name": "User",
            "referral_code": self.referrer_code,
        }

        # Register the user
        response = self.client.post("/api/auth/register/", registration_data)
        self.assertEqual(response.status_code, 201)

        # Check that user was created
        new_user = User.objects.get(email="newuser@example.com")
        self.assertIsNotNone(new_user)

        # Check that no referral signup was created
        referral_signup_count = ReferralSignup.objects.filter(
            referrer=self.referrer, referred=new_user
        ).count()
        self.assertEqual(referral_signup_count, 0)

    def test_user_registration_with_invalid_referral_code_ignores_silently(self):
        """Test that registering with invalid referral code still works but no signup created"""
        registration_data = {
            "email": "newuser2@example.com",
            "password1": "testpassword123!",
            "password2": "testpassword123!",
            "first_name": "Test",
            "last_name": "User",
            "referral_code": "invalid-code",
        }

        # Register the user
        response = self.client.post("/api/auth/register/", registration_data)
        self.assertEqual(response.status_code, 201)

        # Check that user was created
        new_user = User.objects.get(email="newuser2@example.com")
        self.assertIsNotNone(new_user)

        # Check that no referral signup was created
        referral_signup_count = ReferralSignup.objects.filter(referred=new_user).count()
        self.assertEqual(referral_signup_count, 0)

    def test_user_registration_without_referral_code_works_normally(self):
        """Test that normal registration without referral code still works"""
        registration_data = {
            "email": "newuser3@example.com",
            "password1": "testpassword123!",
            "password2": "testpassword123!",
            "first_name": "Test",
            "last_name": "User",
        }

        # Register the user
        response = self.client.post("/api/auth/register/", registration_data)
        self.assertEqual(response.status_code, 201)

        # Check that user was created
        new_user = User.objects.get(email="newuser3@example.com")
        self.assertIsNotNone(new_user)

        # Check that no referral signup was created
        referral_signup_count = ReferralSignup.objects.filter(referred=new_user).count()
        self.assertEqual(referral_signup_count, 0)

    def test_user_registration_with_empty_referral_code_works_normally(self):
        """Test that registration with empty referral code works normally"""
        registration_data = {
            "email": "newuser4@example.com",
            "password1": "testpassword123!",
            "password2": "testpassword123!",
            "first_name": "Test",
            "last_name": "User",
            "referral_code": "",
        }

        # Register the user
        response = self.client.post("/api/auth/register/", registration_data)
        self.assertEqual(response.status_code, 201)

        # Check that user was created
        new_user = User.objects.get(email="newuser4@example.com")
        self.assertIsNotNone(new_user)

        # Check that no referral signup was created
        referral_signup_count = ReferralSignup.objects.filter(referred=new_user).count()
        self.assertEqual(referral_signup_count, 0)
