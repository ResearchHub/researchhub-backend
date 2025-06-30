from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APITestCase

from paper.tests.helpers import create_paper
from purchase.models import Balance, Fundraise
from purchase.services.fundraise_service import FundraiseService
from reputation.models import BountyFee, SupportFee
from researchhub_document.helpers import create_post
from user.tests.helpers import create_random_authenticated_user, create_user


class LockedBalanceTests(APITestCase, TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("test_user")
        self.bountyFee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)
        self.supportFee = SupportFee.objects.create(rh_pct=0.03, dao_pct=0.00)

        # Give user some regular balance
        distribution_content_type = ContentType.objects.get(model="distribution")
        Balance.objects.create(
            amount=1000,
            user=self.user,
            content_type=distribution_content_type,
            is_locked=False,
        )

        # Give user some locked balance
        Balance.objects.create(
            amount=500,
            user=self.user,
            content_type=distribution_content_type,
            is_locked=True,
            lock_type="FUNDRAISE_CONTRIBUTION",
        )

        self.client.force_authenticate(self.user)

    def test_get_balance_methods(self):
        # Test that balance methods return correct values
        self.assertEqual(
            self.user.get_balance(include_locked=True), 1500
        )  # Total balance including locked
        self.assertEqual(
            self.user.get_available_balance(), 1000
        )  # Default excludes locked
        self.assertEqual(self.user.get_available_balance(), 1000)  # Available balance
        self.assertEqual(self.user.get_locked_balance(), 500)  # Locked balance

    def test_cannot_withdraw_locked_balance(self):
        # Try to withdraw more than available balance (but less than total)
        response = self.client.post(
            "/api/withdrawal/",
            {
                "amount": "1200",  # More than available (1000) but less than total (1500)
                "to_address": "0x1234567890123456789012345678901234567890",
                "network": "BASE",
                "agreed_to_terms": True,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("do not have enough RSC", response.data)

    def test_cannot_create_bounty_with_locked_balance(self):
        # Create a paper to add bounty to
        paper = create_paper()

        # Try to create bounty that would require locked funds
        response = self.client.post(
            "/api/bounty/",
            {
                "amount": 1100,  # More than available balance
                "bounty_type": "REVIEW",
                "item_object_id": paper.id,
                "item_content_type": ContentType.objects.get_for_model(paper).id,
            },
        )
        self.assertEqual(response.status_code, 402)
        self.assertIn("Insufficient Funds", response.data["detail"])

    def test_cannot_purchase_with_locked_balance(self):
        # Create a post to support
        post = create_post(created_by=self.user)

        # Try to create a purchase/support that would require locked funds
        response = self.client.post(
            "/api/purchase/",
            {
                "amount": 1100,
                "object_id": post.id,
                "content_type": "researchhubpost",
                "purchase_method": "OFF_CHAIN",
                "purchase_type": "BOOST",
            },
        )
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.data, "Insufficient Funds")

    # Skip this test as Support model has a different flow
    # The balance check is done in the create method which we've already updated
    # def test_cannot_support_with_locked_balance(self):
    #     pass

    def test_cannot_contribute_to_fundraise_with_locked_balance(self):
        # Create a post and fundraise
        post = create_post(created_by=self.user)
        fundraise_service = FundraiseService()
        fundraise = fundraise_service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=post.unified_document,
            goal_amount=10000,
            goal_currency="RSC",
            status=Fundraise.OPEN,
        )

        # Try to contribute more than available balance
        response = self.client.post(
            f"/api/fundraise/{fundraise.id}/contribute/",
            {"amount": 1100, "contribution_type": "CRYPTO"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Insufficient balance", response.data["message"])

    def test_can_spend_within_available_balance(self):
        # Create a paper to add bounty to
        paper = create_paper()

        # Create bounty within available balance
        response = self.client.post(
            "/api/bounty/",
            {
                "amount": 500,  # Within available balance
                "bounty_type": "REVIEW",
                "item_object_id": paper.id,
                "item_content_type": ContentType.objects.get_for_model(paper).id,
            },
        )
        self.assertEqual(response.status_code, 201)  # 201 for successful creation

        # Verify balance was deducted properly
        self.user.refresh_from_db()
        # Account for bounty fees (9% total)
        expected_remaining = 1000 - 500 - (500 * 0.09)
        self.assertAlmostEqual(
            float(self.user.get_available_balance()),
            float(expected_remaining),
            places=2,
        )
        # Locked balance should remain unchanged
        self.assertEqual(self.user.get_locked_balance(), 500)
