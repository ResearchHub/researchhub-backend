from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from rest_framework.exceptions import PermissionDenied

from purchase.services.tip_service import TipService
from user.related_models.user_model import FOUNDATION_EMAIL
from user.tests.helpers import create_random_default_user, create_user


class TipServiceTests(TestCase):
    def setUp(self):
        self.service = TipService()

    def test_foundation_account_can_tip(self):
        # Arrange
        foundation = create_user(email=FOUNDATION_EMAIL)

        # Act
        allowed = self.service.can_tip(foundation)

        # Assert
        self.assertTrue(allowed)

    def test_ordinary_user_cannot_tip(self):
        # Arrange
        create_user(email=FOUNDATION_EMAIL)
        user = create_random_default_user("ordinary")

        # Act
        allowed = self.service.can_tip(user)

        # Assert
        self.assertFalse(allowed)

    def test_moderator_and_staff_cannot_tip(self):
        # Arrange
        create_user(email=FOUNDATION_EMAIL)
        moderator = create_random_default_user("moderator", moderator=True)
        staff = create_random_default_user("staff")
        staff.is_staff = True
        staff.is_superuser = True
        staff.save()

        for user in (moderator, staff):
            with self.subTest(user=user.email):
                # Act
                allowed = self.service.can_tip(user)

                # Assert
                self.assertFalse(allowed)

    def test_unauthenticated_callers_cannot_tip(self):
        # Arrange
        create_user(email=FOUNDATION_EMAIL)

        for user in (None, AnonymousUser()):
            with self.subTest(user=user):
                # Act
                allowed = self.service.can_tip(user)

                # Assert
                self.assertFalse(allowed)

    def test_fallback_account_cannot_tip_when_no_foundation_account_exists(self):
        """Without a Foundation user the community account resolves to the bank."""
        # Arrange
        bank = create_user(email="bank@researchhub.com")

        # Act
        allowed = self.service.can_tip(bank)

        # Assert
        self.assertFalse(allowed)

    def test_removed_foundation_account_cannot_tip(self):
        # Arrange
        create_user(email="bank@researchhub.com")
        foundation = create_user(email=FOUNDATION_EMAIL)
        foundation.delete()

        # Act
        allowed = self.service.can_tip(foundation)

        # Assert
        self.assertFalse(allowed)

    def test_ensure_can_tip_raises_for_other_accounts(self):
        # Arrange
        create_user(email=FOUNDATION_EMAIL)
        user = create_random_default_user("ordinary")

        # Act / Assert
        with self.assertRaises(PermissionDenied):
            self.service.ensure_can_tip(user)

    def test_ensure_can_tip_passes_for_foundation_account(self):
        # Arrange
        foundation = create_user(email=FOUNDATION_EMAIL)

        # Act
        result = self.service.ensure_can_tip(foundation)

        # Assert
        self.assertIsNone(result)
