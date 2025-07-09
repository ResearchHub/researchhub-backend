import uuid
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from referral.models import ReferralSignup
from user.models import User


class ReferralAssignmentViewSetTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create test users
        self.referrer = User.objects.create_user(
            username="referrer",
            email="referrer@test.com",
            password=uuid.uuid4().hex,
        )

        self.regular_user = User.objects.create_user(
            username="regular_user",
            email="regular@test.com",
            password=uuid.uuid4().hex,
        )

        self.moderator = User.objects.create_user(
            username="moderator",
            email="mod@test.com",
            password=uuid.uuid4().hex,
            moderator=True,
        )

        self.admin = User.objects.create_user(
            username="admin",
            email="admin@test.com",
            password=uuid.uuid4().hex,
            is_staff=True,
        )

        # Create users with different signup times
        self.recent_user = User.objects.create_user(
            username="recent_user",
            email="recent@test.com",
            password=uuid.uuid4().hex,
        )
        # Set date_joined to 30 minutes ago
        self.recent_user.date_joined = timezone.now() - timedelta(minutes=30)
        self.recent_user.save()

        self.old_user = User.objects.create_user(
            username="old_user",
            email="old@test.com",
            password=uuid.uuid4().hex,
        )
        # Set date_joined to 2 hours ago
        self.old_user.date_joined = timezone.now() - timedelta(hours=2)
        self.old_user.save()

        self.url = reverse("referral:referral-assignment-add-referral-code")

    def test_unauthenticated_request_fails(self):
        """Test that unauthenticated requests are rejected."""
        response = self.client.post(
            self.url,
            {
                "user_id": self.recent_user.id,
                "referral_code": self.referrer.referral_code,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_regular_user_can_add_referral_to_themselves(self):
        """Test that regular users can add referral codes to their own account if recently joined."""
        # Create a new user that just joined
        new_user = User.objects.create_user(
            username="new_user",
            email="new@test.com",
            password=uuid.uuid4().hex,
        )
        self.client.force_authenticate(user=new_user)

        response = self.client.post(
            self.url,
            {
                "user_id": new_user.id,
                "referral_code": self.referrer.referral_code,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["message"], "Referral code successfully added.")

        # Verify referral signup was created
        self.assertTrue(
            ReferralSignup.objects.filter(
                referrer=self.referrer, referred=new_user
            ).exists()
        )

        # Verify invited_by was set
        new_user.refresh_from_db()
        self.assertEqual(new_user.invited_by, self.referrer)

    def test_regular_user_cannot_add_referral_to_other_user(self):
        """Test that regular users cannot add referral codes to other users' accounts."""
        self.client.force_authenticate(user=self.regular_user)

        response = self.client.post(
            self.url,
            {
                "user_id": self.recent_user.id,
                "referral_code": self.referrer.referral_code,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["detail"],
            "You can only add referral codes to your own account.",
        )

    def test_regular_user_cannot_add_referral_to_themselves_if_old(self):
        """Test that regular users cannot add referral codes to themselves if they joined over an hour ago."""
        self.client.force_authenticate(user=self.old_user)

        response = self.client.post(
            self.url,
            {
                "user_id": self.old_user.id,
                "referral_code": self.referrer.referral_code,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["detail"],
            "Can only add referral codes to users who joined within the last hour.",
        )

    def test_moderator_can_add_referral_to_old_user(self):
        """Test that moderators can add referral codes retroactively."""
        self.client.force_authenticate(user=self.moderator)

        response = self.client.post(
            self.url,
            {
                "user_id": self.old_user.id,
                "referral_code": self.referrer.referral_code,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["message"], "Referral code successfully added.")

        # Verify referral signup was created
        self.assertTrue(
            ReferralSignup.objects.filter(
                referrer=self.referrer, referred=self.old_user
            ).exists()
        )

    def test_admin_can_add_referral_to_old_user(self):
        """Test that admins can add referral codes retroactively."""
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            self.url,
            {
                "user_id": self.old_user.id,
                "referral_code": self.referrer.referral_code,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["message"], "Referral code successfully added.")

    def test_invalid_user_id(self):
        """Test that invalid user IDs are rejected."""
        self.client.force_authenticate(user=self.regular_user)

        response = self.client.post(
            self.url,
            {
                "user_id": 99999,
                "referral_code": self.referrer.referral_code,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("User not found", str(response.data))

    def test_invalid_referral_code(self):
        """Test that invalid referral codes are rejected."""
        self.client.force_authenticate(user=self.regular_user)

        response = self.client.post(
            self.url,
            {
                "user_id": self.recent_user.id,
                "referral_code": "invalid-code",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid referral code", str(response.data))

    def test_self_referral_rejected(self):
        """Test that users cannot refer themselves."""
        self.client.force_authenticate(user=self.regular_user)

        response = self.client.post(
            self.url,
            {
                "user_id": self.referrer.id,
                "referral_code": self.referrer.referral_code,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Users cannot refer themselves", str(response.data))

    def test_duplicate_referral_rejected(self):
        """Test that users cannot be referred multiple times."""
        # Create a new user that just joined
        new_user = User.objects.create_user(
            username="new_user3",
            email="new3@test.com",
            password=uuid.uuid4().hex,
        )
        self.client.force_authenticate(user=new_user)

        # First referral should succeed
        response = self.client.post(
            self.url,
            {
                "user_id": new_user.id,
                "referral_code": self.referrer.referral_code,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Second referral should fail
        another_referrer = User.objects.create_user(
            username="another_referrer",
            email="another@test.com",
            password=uuid.uuid4().hex,
        )

        response = self.client.post(
            self.url,
            {
                "user_id": new_user.id,
                "referral_code": another_referrer.referral_code,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("This user has already been referred", str(response.data))

    def test_response_includes_referral_details(self):
        """Test that the response includes full referral signup details."""
        # Create a new user that just joined
        new_user = User.objects.create_user(
            username="new_user2",
            email="new2@test.com",
            password=uuid.uuid4().hex,
        )
        self.client.force_authenticate(user=new_user)

        response = self.client.post(
            self.url,
            {
                "user_id": new_user.id,
                "referral_code": self.referrer.referral_code,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("referral_signup", response.data)

        referral_data = response.data["referral_signup"]
        self.assertEqual(referral_data["referrer"], self.referrer.id)
        self.assertEqual(referral_data["referrer_username"], self.referrer.username)
        self.assertEqual(referral_data["referred"], new_user.id)
        self.assertEqual(referral_data["referred_username"], new_user.username)
        self.assertIn("signup_date", referral_data)

    def test_invited_by_not_overwritten_if_already_set(self):
        """Test that invited_by field is not overwritten if already set."""
        # Create a new user that just joined
        new_user = User.objects.create_user(
            username="new_user4",
            email="new4@test.com",
            password=uuid.uuid4().hex,
        )

        # Set invited_by to a different user
        other_user = User.objects.create_user(
            username="other_user",
            email="other@test.com",
            password=uuid.uuid4().hex,
        )
        new_user.invited_by = other_user
        new_user.save()

        self.client.force_authenticate(user=new_user)

        response = self.client.post(
            self.url,
            {
                "user_id": new_user.id,
                "referral_code": self.referrer.referral_code,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify invited_by was NOT changed
        new_user.refresh_from_db()
        self.assertEqual(new_user.invited_by, other_user)
        self.assertNotEqual(new_user.invited_by, self.referrer)
