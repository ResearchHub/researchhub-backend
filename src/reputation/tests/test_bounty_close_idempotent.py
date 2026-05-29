import decimal
from datetime import datetime
from unittest.mock import patch

import pytz
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from reputation.models import Bounty, BountyFee, Escrow
from researchhub_comment.tests.helpers import create_rh_comment
from user.tests.helpers import create_random_default_user


class BountyCloseIdempotentTests(TestCase):
    def setUp(self):
        BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)
        self.funder_a = create_random_default_user("bounty_close_funder_a")
        self.funder_b = create_random_default_user("bounty_close_funder_b")
        self.comment = create_rh_comment(created_by=self.funder_a)
        content_type = ContentType.objects.get_for_model(self.comment)

        self.escrow = Escrow.objects.create(
            hold_type=Escrow.BOUNTY,
            amount_holding=decimal.Decimal("100"),
            created_by=self.funder_a,
            content_type=content_type,
            object_id=self.comment.id,
        )
        self.parent_bounty = Bounty.objects.create(
            amount=decimal.Decimal("50"),
            created_by=self.funder_a,
            escrow=self.escrow,
            item_content_type=content_type,
            item_object_id=self.comment.id,
            unified_document=self.comment.unified_document,
            status=Bounty.ASSESSMENT,
            expiration_date=datetime.now(pytz.UTC),
        )
        self.child_bounty = Bounty.objects.create(
            amount=decimal.Decimal("50"),
            created_by=self.funder_b,
            escrow=self.escrow,
            parent=self.parent_bounty,
            item_content_type=content_type,
            item_object_id=self.comment.id,
            unified_document=self.comment.unified_document,
            status=Bounty.ASSESSMENT,
            expiration_date=datetime.now(pytz.UTC),
        )

    @patch("reputation.related_models.escrow.Escrow.refund")
    def test_close_rolls_back_partial_refunds_on_failure(self, mock_refund):
        """A failed refund mid-close must not leave prior refunds committed."""
        original_refund = Escrow.refund

        def refund_side_effect(escrow_self, recipient, amount, status=None, is_locked=False):
            if recipient.id == self.funder_b.id:
                return False
            return original_refund(
                escrow_self, recipient, amount, status=status, is_locked=is_locked
            )

        mock_refund.side_effect = refund_side_effect

        closed = self.parent_bounty.close(Bounty.EXPIRED)
        self.assertFalse(closed)

        self.escrow.refresh_from_db()
        self.assertEqual(self.escrow.amount_holding, decimal.Decimal("100"))

        from reputation.models import Distribution

        refund_count = Distribution.objects.filter(
            distribution_type="BOUNTY_REFUND", recipient=self.funder_a
        ).count()
        self.assertEqual(refund_count, 0)

    def test_close_is_idempotent_after_success(self):
        closed_first = self.parent_bounty.close(Bounty.EXPIRED)
        self.assertTrue(closed_first)

        self.escrow.refresh_from_db()
        holding_after_first = self.escrow.amount_holding

        closed_second = self.parent_bounty.close(Bounty.EXPIRED)
        self.assertTrue(closed_second)

        self.escrow.refresh_from_db()
        self.assertEqual(self.escrow.amount_holding, holding_after_first)
