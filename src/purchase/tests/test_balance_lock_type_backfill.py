from decimal import Decimal
from importlib import import_module

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from purchase.models import Balance, Fundraise, Purchase
from reputation.models import BountyFee, Distribution, Escrow
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user

_migration = import_module("purchase.migrations.0058_backfill_balance_lock_type")
backfill_lock_type = _migration.backfill_lock_type


class BalanceLockTypeBackfillTest(TestCase):
    def setUp(self):
        self.owner = create_random_authenticated_user("backfill_owner")
        self.contributor = create_random_authenticated_user("backfill_contributor")
        self.fee = BountyFee.objects.create(rh_pct=Decimal("0.07"), dao_pct=0)
        document = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        self.fundraise = Fundraise.objects.create(
            created_by=self.owner,
            unified_document=document,
            goal_amount=100,
            goal_currency="USD",
            status=Fundraise.OPEN,
        )
        self.escrow = Escrow.objects.create(
            created_by=self.owner,
            hold_type=Escrow.FUNDRAISE,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            bounty_fee=self.fee,
        )
        self.fundraise.escrow = self.escrow
        self.fundraise.save(update_fields=["escrow"])

        self.distribution_ct = ContentType.objects.get_for_model(Distribution)
        self.purchase_ct = ContentType.objects.get_for_model(Purchase)
        self.bounty_fee_ct = ContentType.objects.get_for_model(BountyFee)
        self.escrow_ct = ContentType.objects.get_for_model(Escrow)

    def _create_fundraise_purchase(self):
        return Purchase.objects.create(
            user=self.contributor,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount="80",
        )

    def _create_distribution(self, distribution_type, amount, **kwargs):
        return Distribution.objects.create(
            recipient=self.contributor,
            distribution_type=distribution_type,
            amount=amount,
            **kwargs,
        )

    def test_backfill_labels_legacy_fundraise_debit_before_allocating_promo(self):
        # Arrange
        funding_credit = self._create_distribution("PURCHASE", 100)
        credit_balance = Balance.objects.create(
            user=self.contributor,
            content_type=self.distribution_ct,
            object_id=funding_credit.id,
            amount="100",
            is_locked=True,
        )
        contribution = self._create_fundraise_purchase()
        debit_balance = Balance.objects.create(
            user=self.contributor,
            content_type=self.purchase_ct,
            object_id=contribution.id,
            amount="-80",
            is_locked=True,
        )

        # Act
        backfill_lock_type(apps, None)
        Balance.objects.create(
            user=self.contributor,
            content_type=self.distribution_ct,
            amount="100",
            is_locked=True,
            lock_type=Balance.LockType.PROMOTIONAL,
        )
        allocations, remaining = self.contributor.allocate_locked_spend(Decimal(100))

        # Assert
        credit_balance.refresh_from_db()
        debit_balance.refresh_from_db()
        self.assertEqual(credit_balance.lock_type, Balance.LockType.FUNDING_CREDIT)
        self.assertEqual(debit_balance.lock_type, Balance.LockType.FUNDING_CREDIT)
        self.assertEqual(remaining, Decimal(0))
        self.assertEqual(
            [
                (allocation["lock_type"], allocation["amount"])
                for allocation in allocations
            ],
            [
                (Balance.LockType.FUNDING_CREDIT, Decimal(20)),
                (Balance.LockType.PROMOTIONAL, Decimal(80)),
            ],
        )

    def test_backfill_labels_legacy_fundraise_fee_and_refund_movements(self):
        # Arrange
        fee_debit = Balance.objects.create(
            user=self.contributor,
            content_type=self.bounty_fee_ct,
            object_id=self.fee.id,
            amount="-2",
            is_locked=True,
        )
        principal_refund = self._create_distribution(
            "BOUNTY_REFUND",
            80,
            proof_item_content_type=self.escrow_ct,
            proof_item_object_id=self.escrow.id,
        )
        principal_refund_balance = Balance.objects.create(
            user=self.contributor,
            content_type=self.distribution_ct,
            object_id=principal_refund.id,
            amount="80",
            is_locked=True,
        )
        fee_refund = self._create_distribution(
            "BOUNTY_REFUND",
            2,
            proof_item_content_type=self.bounty_fee_ct,
            proof_item_object_id=self.fee.id,
        )
        fee_refund_balance = Balance.objects.create(
            user=self.contributor,
            content_type=self.distribution_ct,
            object_id=fee_refund.id,
            amount="2",
            is_locked=True,
        )
        unrelated_refund = self._create_distribution("BOUNTY_REFUND", 10)
        unrelated_refund_balance = Balance.objects.create(
            user=self.contributor,
            content_type=self.distribution_ct,
            object_id=unrelated_refund.id,
            amount="10",
            is_locked=True,
        )

        # Act
        backfill_lock_type(apps, None)

        # Assert
        for balance in (fee_debit, principal_refund_balance, fee_refund_balance):
            balance.refresh_from_db()
            self.assertEqual(balance.lock_type, Balance.LockType.FUNDING_CREDIT)
        unrelated_refund_balance.refresh_from_db()
        self.assertIsNone(unrelated_refund_balance.lock_type)
