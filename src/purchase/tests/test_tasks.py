from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.test import TestCase

from purchase.models import Fundraise
from purchase.services.fundraise_service import FundraiseService
from purchase.tasks import complete_eligible_fundraises
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.tests.helpers import create_random_authenticated_user, create_user


class FundraiseTasksTest(TestCase):
    def setUp(self):
        # Create a moderator user
        self.user = create_random_authenticated_user("fundraise_tasks", moderator=True)

        # Create a post
        self.post = create_post(created_by=self.user, document_type=PREREGISTRATION)

        # Set up service
        self.fundraise_service = FundraiseService()

        # Create required exchange rate for USD to RSC conversion
        from purchase.models import RscExchangeRate

        self.rsc_exchange_rate = RscExchangeRate.objects.create(
            rate=0.5,  # 1 USD = 2 RSC
            real_rate=0.5,
            price_source="COIN_GECKO",
            target_currency="USD",
        )

        # Create required bounty fee for fee calculations
        from reputation.models import BountyFee

        self.bounty_fee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)

        # Create bank user that's needed for fee calculations
        self.bank_user = create_user(email="bank@researchhub.com")

    def test_complete_eligible_fundraises_success(self):
        """Test that eligible fundraises are automatically completed"""
        # Create a fundraise that's more than a week old
        fundraise = self.fundraise_service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=self.post.unified_document,
            goal_amount=Decimal("100.00"),
            goal_currency="USD",
            status=Fundraise.OPEN,
        )

        # Manually set the start_date to be more than a week old
        old_date = datetime.now(pytz.UTC) - timedelta(days=8)
        fundraise.start_date = old_date
        fundraise.save()

        # Add funds to escrow to simulate reaching the goal
        # Goal is $100 USD, with rate 0.5 that means we need 200 RSC
        fundraise.escrow.amount_holding = Decimal("200.00")  # More than goal of $100
        fundraise.escrow.save()

        # Verify initial state
        self.assertEqual(fundraise.status, Fundraise.OPEN)
        self.assertEqual(fundraise.escrow.amount_holding, Decimal("200.00"))
        self.assertEqual(fundraise.escrow.amount_paid, Decimal("0.00"))

        # Run the task
        result = complete_eligible_fundraises()

        # Verify the task processed the fundraise
        self.assertEqual(result["completed_count"], 1)
        self.assertEqual(result["error_count"], 0)

        # Verify the fundraise was completed
        fundraise.refresh_from_db()
        self.assertEqual(fundraise.status, Fundraise.COMPLETED)
        self.assertEqual(fundraise.escrow.amount_holding, Decimal("0.00"))
        self.assertEqual(fundraise.escrow.amount_paid, Decimal("200.00"))

    def test_complete_eligible_fundraises_goal_not_met(self):
        """Test that fundraises that haven't met their goal are not completed"""
        # Create a fundraise that's more than a week old
        fundraise = self.fundraise_service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=self.post.unified_document,
            goal_amount=Decimal("100.00"),
            goal_currency="USD",
            status=Fundraise.OPEN,
        )

        # Manually set the start_date to be more than a week old
        old_date = datetime.now(pytz.UTC) - timedelta(days=8)
        fundraise.start_date = old_date
        fundraise.save()

        # Add insufficient funds to escrow (less than goal)
        # Goal is $100 USD, with rate 0.5 that means we need 200 RSC for goal
        fundraise.escrow.amount_holding = Decimal("100.00")  # Only 100 RSC = $50 USD
        fundraise.escrow.save()

        # Verify initial state
        self.assertEqual(fundraise.status, Fundraise.OPEN)

        # Run the task
        result = complete_eligible_fundraises()

        # Verify the task did not process the fundraise
        self.assertEqual(result["completed_count"], 0)
        self.assertEqual(result["error_count"], 0)

        # Verify the fundraise remains open
        fundraise.refresh_from_db()
        self.assertEqual(fundraise.status, Fundraise.OPEN)
        self.assertEqual(fundraise.escrow.amount_holding, Decimal("100.00"))
        self.assertEqual(fundraise.escrow.amount_paid, Decimal("0.00"))

    def test_complete_eligible_fundraises_too_new(self):
        """Test that fundraises less than a week old are not completed"""
        # Create a recent fundraise
        fundraise = self.fundraise_service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=self.post.unified_document,
            goal_amount=Decimal("100.00"),
            goal_currency="USD",
            status=Fundraise.OPEN,
        )

        # Add funds to escrow to simulate reaching the goal
        fundraise.escrow.amount_holding = Decimal("200.00")  # More than goal of $100
        fundraise.escrow.save()

        # Verify initial state
        self.assertEqual(fundraise.status, Fundraise.OPEN)

        # Run the task
        result = complete_eligible_fundraises()

        # Verify the task did not process the fundraise (too new)
        self.assertEqual(result["completed_count"], 0)
        self.assertEqual(result["error_count"], 0)

        # Verify the fundraise remains open
        fundraise.refresh_from_db()
        self.assertEqual(fundraise.status, Fundraise.OPEN)
        self.assertEqual(fundraise.escrow.amount_holding, Decimal("200.00"))
        self.assertEqual(fundraise.escrow.amount_paid, Decimal("0.00"))
