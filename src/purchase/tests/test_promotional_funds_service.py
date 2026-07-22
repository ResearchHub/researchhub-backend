from decimal import Decimal

from django.test import TestCase

from purchase.related_models.balance_model import Balance
from purchase.services.promotional_funds_service import PromotionalFundsService
from user.tests.helpers import create_user


class PromotionalFundsServiceTest(TestCase):
    def setUp(self):
        self.service = PromotionalFundsService()
        self.user = create_user(email="promo@test.com")

    def test_grant_creates_promotional_locked_balance(self):
        # Arrange
        amount = Decimal(100)

        # Act
        record = self.service.grant(self.user, amount, reason="launch campaign")

        # Assert
        self.assertEqual(record.distribution_type, "PROMOTIONAL_CREDIT")
        self.assertEqual(record.recipient, self.user)
        self.assertEqual(record.reputation_amount, 0)
        self.assertEqual(record.proof["reason"], "launch campaign")

        balance = Balance.objects.get(user=self.user)
        self.assertTrue(balance.is_locked)
        self.assertEqual(balance.lock_type, Balance.LockType.PROMOTIONAL)
        self.assertEqual(Decimal(balance.amount), amount)

    def test_granted_funds_are_promotional_and_not_withdrawable(self):
        # Arrange
        self.service.grant(self.user, Decimal(75), reason="signup bonus")

        # Act / Assert
        self.assertEqual(self.user.get_promotional_balance(), Decimal(75))
        self.assertEqual(self.user.get_available_balance(), Decimal(0))
        self.assertEqual(self.user.get_funding_credits_balance(), Decimal(0))

    def test_grant_rejects_non_positive_amount(self):
        # Act / Assert
        with self.assertRaises(ValueError):
            self.service.grant(self.user, Decimal(0), reason="campaign")
        with self.assertRaises(ValueError):
            self.service.grant(self.user, Decimal(-5), reason="campaign")

    def test_grant_rejects_non_finite_amount(self):
        # Act / Assert
        for amount in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.service.grant(self.user, amount, reason="campaign")

        self.assertFalse(Balance.objects.filter(user=self.user).exists())

    def test_grant_requires_reason(self):
        # Act / Assert
        with self.assertRaises(ValueError):
            self.service.grant(self.user, Decimal(10), reason="  ")
