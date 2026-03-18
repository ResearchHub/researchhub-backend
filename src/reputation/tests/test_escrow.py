from decimal import Decimal

from django.test import TestCase

from purchase.models import Balance
from reputation.related_models.escrow import Escrow
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class EscrowRefundTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="escrow_user", password="testpass"
        )
        self.unified_document = ResearchhubUnifiedDocument.objects.create()
        self.escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            amount_holding=Decimal("500"),
            item=self.unified_document,
        )

    def test_refund_zero_amount_returns_true_immediately(self):
        result = self.escrow.refund(self.user, Decimal("0"))

        self.assertTrue(result)
        self.escrow.refresh_from_db()
        self.assertEqual(self.escrow.amount_holding, Decimal("500"))

    def test_refund_exceeding_holding_returns_false(self):
        result = self.escrow.refund(self.user, Decimal("600"))

        self.assertFalse(result)
        self.escrow.refresh_from_db()
        self.assertEqual(self.escrow.amount_holding, Decimal("500"))

    def test_refund_success_reduces_amount_holding(self):
        result = self.escrow.refund(self.user, Decimal("200"))

        self.assertTrue(result)
        self.escrow.refresh_from_db()
        self.assertEqual(self.escrow.amount_holding, Decimal("300"))

    def test_refund_creates_balance_record(self):
        initial_count = Balance.objects.filter(user=self.user).count()

        self.escrow.refund(self.user, Decimal("100"))

        new_count = Balance.objects.filter(user=self.user).count()
        self.assertEqual(new_count, initial_count + 1)

        balance = Balance.objects.filter(user=self.user).latest("id")
        self.assertEqual(balance.amount, "100")

    def test_refund_full_amount(self):
        result = self.escrow.refund(self.user, Decimal("500"))

        self.assertTrue(result)
        self.escrow.refresh_from_db()
        self.assertEqual(self.escrow.amount_holding, Decimal("0"))

    def test_refund_sets_cancelled_status_when_pending(self):
        self.assertEqual(self.escrow.status, Escrow.PENDING)

        self.escrow.refund(
            self.user, Decimal("200"), status=Escrow.CANCELLED
        )

        self.escrow.refresh_from_db()
        self.assertEqual(self.escrow.status, Escrow.CANCELLED)

    def test_refund_sets_expired_status(self):
        self.escrow.refund(
            self.user, Decimal("200"), status=Escrow.EXPIRED
        )

        self.escrow.refresh_from_db()
        self.assertEqual(self.escrow.status, Escrow.EXPIRED)

    def test_refund_does_not_change_paid_status(self):
        self.escrow.set_paid_status()
        self.assertEqual(self.escrow.status, Escrow.PAID)

        self.escrow.refund(
            self.user, Decimal("200"), status=Escrow.CANCELLED
        )

        self.escrow.refresh_from_db()
        self.assertEqual(self.escrow.status, Escrow.PAID)

    def test_multiple_sequential_refunds(self):
        self.escrow.refund(self.user, Decimal("100"))
        self.escrow.refund(self.user, Decimal("150"))
        self.escrow.refund(self.user, Decimal("50"))

        self.escrow.refresh_from_db()
        self.assertEqual(self.escrow.amount_holding, Decimal("200"))

    def test_refund_to_different_recipient(self):
        other_user = User.objects.create_user(
            username="other_user", password="testpass"
        )

        result = self.escrow.refund(other_user, Decimal("100"))

        self.assertTrue(result)
        balance = Balance.objects.filter(user=other_user).latest("id")
        self.assertEqual(balance.amount, "100")
