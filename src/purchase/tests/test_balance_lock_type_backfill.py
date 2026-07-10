from importlib import import_module

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from paper.related_models.paper_model import Paper
from purchase.related_models.balance_model import Balance
from purchase.related_models.rsc_purchase_fee import RscPurchaseFee
from reputation.related_models.distribution import Distribution
from user.tests.helpers import create_user

# The module name starts with a digit, so it cannot be imported with a
# regular import statement.
_migration = import_module("purchase.migrations.0058_backfill_balance_lock_type")
backfill_lock_type = _migration.backfill_lock_type
reverse_backfill = _migration.reverse_backfill


class BalanceLockTypeBackfillTest(TestCase):
    def setUp(self):
        self.user = create_user(email="backfill@test.com")
        self.dist_ct = ContentType.objects.get_for_model(Distribution)

    def _create_locked_from_distribution(self, distribution_type, amount="100"):
        distribution = Distribution.objects.create(
            recipient=self.user,
            amount=100,
            distribution_type=distribution_type,
        )
        return Balance.objects.create(
            user=self.user,
            amount=amount,
            content_type=self.dist_ct,
            object_id=distribution.id,
            is_locked=True,
        )

    def test_backfill_labels_locked_rows_by_source(self):
        # Arrange
        purchase_row = self._create_locked_from_distribution("PURCHASE")
        referral_row = self._create_locked_from_distribution("REFERRAL_BONUS")
        yield_row = self._create_locked_from_distribution("STAKING_YIELD")

        fee = RscPurchaseFee.objects.create(rh_pct=0.02, dao_pct=0.00)
        fee_row = Balance.objects.create(
            user=self.user,
            amount="-2",
            content_type=ContentType.objects.get_for_model(RscPurchaseFee),
            object_id=fee.id,
            is_locked=True,
        )

        unlocked_row = Balance.objects.create(
            user=self.user,
            amount="50",
            content_type=self.dist_ct,
            is_locked=False,
        )
        unrelated_locked_row = Balance.objects.create(
            user=self.user,
            amount="10",
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=1,
            is_locked=True,
        )

        # Act
        backfill_lock_type(apps, None)

        # Assert
        purchase_row.refresh_from_db()
        referral_row.refresh_from_db()
        yield_row.refresh_from_db()
        fee_row.refresh_from_db()
        unlocked_row.refresh_from_db()
        unrelated_locked_row.refresh_from_db()
        self.assertEqual(purchase_row.lock_type, Balance.LockType.FUNDING_CREDIT)
        self.assertEqual(referral_row.lock_type, Balance.LockType.REFERRAL_BONUS)
        self.assertEqual(yield_row.lock_type, Balance.LockType.STAKING_YIELD)
        self.assertEqual(fee_row.lock_type, Balance.LockType.FUNDING_CREDIT)
        self.assertIsNone(unlocked_row.lock_type)
        self.assertIsNone(unrelated_locked_row.lock_type)

    def test_reverse_resets_backfilled_rows_but_keeps_promotional(self):
        # Arrange
        purchase_row = self._create_locked_from_distribution("PURCHASE")
        promotional_row = Balance.objects.create(
            user=self.user,
            amount="25",
            content_type=self.dist_ct,
            is_locked=True,
            lock_type=Balance.LockType.PROMOTIONAL,
        )
        backfill_lock_type(apps, None)

        # Act
        reverse_backfill(apps, None)

        # Assert
        purchase_row.refresh_from_db()
        promotional_row.refresh_from_db()
        self.assertIsNone(purchase_row.lock_type)
        self.assertEqual(promotional_row.lock_type, Balance.LockType.PROMOTIONAL)
