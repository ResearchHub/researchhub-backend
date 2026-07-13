from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from discussion.models import Flag
from paper.tests.helpers import create_paper
from purchase.models import Balance
from reputation.signals import distribute_for_censor_paper
from user.tests.helpers import create_user


class CensoredPaperBalancePenaltyTests(TestCase):
    def setUp(self):
        self.paper_owner = create_user(email="flagged-paper-owner@test.com")
        self.flagger = create_user(email="paper-flagger@test.com")
        self.paper = create_paper(uploaded_by=self.paper_owner)
        Flag.objects.create(
            created_by=self.flagger,
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
            reason="test flag",
        )

    def _give_flagger_balance(self, amount: Decimal) -> None:
        Balance.objects.create(
            user=self.flagger,
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
            amount=str(amount),
        )

    def test_penalty_does_not_make_zero_balance_negative(self):
        # Act
        distribute_for_censor_paper(
            sender=type(self.paper), instance=self.paper, using="default"
        )

        # Assert
        self.assertEqual(self.flagger.get_available_balance(), Decimal(0))

    def test_penalty_is_capped_at_available_balance(self):
        # Arrange
        self._give_flagger_balance(Decimal("0.01"))

        # Act
        distribute_for_censor_paper(
            sender=type(self.paper), instance=self.paper, using="default"
        )

        # Assert
        self.assertEqual(self.flagger.get_available_balance(), Decimal(0))
        penalty = self.flagger.balances.order_by("-id").first()
        self.assertEqual(Decimal(penalty.amount), Decimal("-0.01"))
