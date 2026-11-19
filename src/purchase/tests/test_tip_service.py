from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from purchase.models import Purchase, RscExchangeRate
from purchase.services.tip_service import TipService
from researchhub_comment.constants.rh_comment_thread_types import (
    COMMUNITY_REVIEW,
    PEER_REVIEW,
    REVIEW_COMMENT_TYPES,
    RH_COMMENT_THREAD_TYPES,
)
from researchhub_comment.tests.helpers import create_rh_comment
from user.related_models.user_model import FOUNDATION_EMAIL, User
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

    def test_account_without_foundation_email_cannot_tip(self):
        # Arrange
        user = create_random_default_user("ordinary")

        # Act
        with patch.object(User, "is_rh_community_account", return_value=True):
            allowed = self.service.can_tip(user)

        # Assert
        self.assertFalse(allowed)


class TipRulesTests(TestCase):
    def setUp(self):
        self.service = TipService()
        self.foundation = create_user(email=FOUNDATION_EMAIL)
        self.reviewer = create_random_default_user("reviewer")
        self.review = self._create_comment(COMMUNITY_REVIEW)
        RscExchangeRate.objects.create(rate=0.5, real_rate=0.5, target_currency="USD")

    def _create_comment(self, comment_type):
        comment = create_rh_comment(created_by=self.reviewer)
        comment.comment_type = comment_type
        comment.save()
        return comment

    def _record_tip(
        self, amount, user=None, purchase_type=Purchase.BOOST, age=timedelta(0)
    ):
        purchase = Purchase.objects.create(
            user=user or self.foundation,
            content_type=ContentType.objects.get_for_model(self.review),
            object_id=self.review.id,
            purchase_type=purchase_type,
            purchase_method=Purchase.OFF_CHAIN,
            paid_status=Purchase.PAID,
            amount=str(amount),
        )
        Purchase.objects.filter(id=purchase.id).update(
            created_date=timezone.now() - age
        )

    def _ensure_allowed(self, amount, object_id=None):
        self.service.ensure_tip_allowed(
            self.foundation,
            self.review.id if object_id is None else object_id,
            Decimal(amount),
        )

    def test_review_comment_types_can_be_tipped(self):
        for comment_type in (COMMUNITY_REVIEW, PEER_REVIEW):
            with self.subTest(comment_type=comment_type):
                # Arrange
                comment = self._create_comment(comment_type)

                # Act / Assert
                self._ensure_allowed("100", comment.id)

    def test_other_comment_types_cannot_be_tipped(self):
        other_types = {
            comment_type
            for comment_type, _ in RH_COMMENT_THREAD_TYPES
            if comment_type not in REVIEW_COMMENT_TYPES
        }

        for comment_type in other_types:
            with self.subTest(comment_type=comment_type):
                # Arrange
                comment = self._create_comment(comment_type)

                # Act / Assert
                with self.assertRaisesMessage(
                    ValidationError, TipService.INVALID_TARGET_MESSAGE
                ):
                    self._ensure_allowed("100", comment.id)

    def test_removed_review_cannot_be_tipped(self):
        # Arrange
        self.review.delete()

        # Act / Assert
        with self.assertRaisesMessage(
            ValidationError, TipService.INVALID_TARGET_MESSAGE
        ):
            self._ensure_allowed("100")

    def test_invalid_comment_ids_are_rejected(self):
        for object_id in ("not-a-number", [self.review.id], {"id": self.review.id}):
            # Act / Assert
            with (
                self.subTest(object_id=object_id),
                self.assertRaisesMessage(
                    ValidationError, TipService.INVALID_TARGET_MESSAGE
                ),
            ):
                self._ensure_allowed("100", object_id)

    def test_tip_at_the_per_tip_limit_is_allowed(self):
        # Act / Assert
        self._ensure_allowed("600")

    def test_tip_above_the_per_tip_limit_is_rejected(self):
        # Act / Assert
        with self.assertRaisesMessage(ValidationError, TipService.AMOUNT_LIMIT_MESSAGE):
            self._ensure_allowed("600.01")

    def test_limits_follow_the_latest_exchange_rate(self):
        # Arrange
        RscExchangeRate.objects.create(rate=0.25, real_rate=0.25, target_currency="USD")

        # Act / Assert
        self._ensure_allowed("1200")
        with self.assertRaisesMessage(ValidationError, TipService.AMOUNT_LIMIT_MESSAGE):
            self._ensure_allowed("1200.01")

    def test_tip_reaching_the_daily_limit_is_allowed(self):
        # Arrange
        self._record_tip(9500)

        # Act / Assert
        self._ensure_allowed("500")

    def test_tip_above_the_daily_limit_is_rejected(self):
        # Arrange
        self._record_tip(9500)

        # Act / Assert
        with self.assertRaisesMessage(ValidationError, TipService.DAILY_LIMIT_MESSAGE):
            self._ensure_allowed("500.01")

    def test_daily_limit_does_not_follow_the_exchange_rate(self):
        # Arrange
        RscExchangeRate.objects.create(rate=0.25, real_rate=0.25, target_currency="USD")
        self._record_tip(9500)

        # Act / Assert
        self._ensure_allowed("500")
        with self.assertRaisesMessage(ValidationError, TipService.DAILY_LIMIT_MESSAGE):
            self._ensure_allowed("500.01")

    def test_tip_inside_the_window_counts_toward_the_daily_limit(self):
        # Arrange
        self._record_tip(10000, age=timedelta(hours=23))

        # Act / Assert
        with self.assertRaisesMessage(ValidationError, TipService.DAILY_LIMIT_MESSAGE):
            self._ensure_allowed("10")

    def test_tip_outside_the_window_is_not_counted(self):
        # Arrange
        self._record_tip(10000, age=timedelta(hours=25))

        # Act / Assert
        self._ensure_allowed("10")

    def test_other_purchases_are_not_counted(self):
        # Arrange
        self._record_tip(10000, user=self.reviewer)
        self._record_tip(10000, purchase_type=Purchase.FUNDRAISE_CONTRIBUTION)
        self._record_tip(10000, purchase_type=Purchase.FUNDING_POOL_CONTRIBUTION)

        # Act / Assert
        self._ensure_allowed("10")
