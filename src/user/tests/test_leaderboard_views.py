from datetime import datetime, timedelta

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework.test import APITestCase

from paper.related_models.paper_model import Paper
from purchase.models import Purchase
from reputation.models import Bounty, BountySolution, Distribution
from reputation.related_models.escrow import Escrow, EscrowRecipients
from researchhub_comment.constants.rh_comment_thread_types import PEER_REVIEW
from researchhub_comment.models import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from user.tests.helpers import create_user


class LeaderboardApiTests(APITestCase):
    def setUp(self):
        # Create test users
        self.reviewer1 = create_user(
            email="reviewer1@researchhub.com", first_name="First", last_name="Reviewer"
        )
        self.reviewer2 = create_user(
            email="reviewer2@researchhub.com", first_name="Second", last_name="Reviewer"
        )

        self.funder1 = create_user(
            email="funder1@researchhub.com", first_name="First", last_name="Funder"
        )

        self.funder2 = create_user(
            email="funder2@researchhub.com", first_name="Second", last_name="Funder"
        )

        self.bank = create_user(
            email="bank@researchhub.com", first_name="Bank", last_name="Bank"
        )

        # Create a paper for the review
        self.paper = Paper.objects.create(title="Test Paper")

        # Create thread properly linked to the paper
        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        self.thread = RhCommentThreadModel.objects.create(
            thread_type=PEER_REVIEW,
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            created_by=self.funder1,
        )

        # Create peer review comment
        self.review_comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "Test review"}]},
            comment_type=PEER_REVIEW,
            created_by=self.reviewer1,
            thread=self.thread,
        )

        # Store content types we'll need
        self.comment_content_type = ContentType.objects.get_for_model(RhCommentModel)
        self.purchase_content_type = ContentType.objects.get_for_model(Purchase)

        # Create escrow first, linked to the review comment
        self.escrow = Escrow.objects.create(
            hold_type=Escrow.BOUNTY,
            status=Escrow.PAID,
            amount_holding=100,
            content_type=self.comment_content_type,
            object_id=self.review_comment.id,
            created_by=self.funder1,
        )

        # Then create bounty with escrow reference and unified_document
        self.bounty = Bounty.objects.create(
            bounty_type=Bounty.Type.REVIEW,
            amount=100,
            created_by=self.funder1,
            item_content_type=self.comment_content_type,
            item_object_id=self.review_comment.id,
            escrow=self.escrow,
            unified_document=self.paper.unified_document,
        )

        # Create escrow recipient for reviewer1
        EscrowRecipients.objects.create(
            escrow=self.escrow, user=self.reviewer1, amount=100
        )

        # Create a purchase/tip for reviewer1
        self.purchase = Purchase.objects.create(
            user=self.funder1,
            amount="50",
            paid_status=Purchase.PAID,
            content_type=self.comment_content_type,
            object_id=self.review_comment.id,
        )

        # Create distribution (tip) for reviewer1
        Distribution.objects.create(
            recipient=self.reviewer1,
            giver=self.funder1,
            amount=50,
            distribution_type="PURCHASE",
            proof_item_content_type=self.purchase_content_type,
            proof_item_object_id=self.purchase.id,
        )

        # Create bounty solution linking the bounty to the review comment
        self.bounty_solution = BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.reviewer1,
            content_type=self.comment_content_type,
            object_id=self.review_comment.id,
        )

        today = timezone.now()

        # Create fundraise purchase
        Purchase.objects.create(
            user=self.funder1,
            amount="200",
            paid_status=Purchase.PAID,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            content_type=self.comment_content_type,
            object_id=self.review_comment.id,
            created_date=today,
        )

        # Create boost purchase
        Purchase.objects.create(
            user=self.funder1,
            amount="100",
            paid_status=Purchase.PAID,
            purchase_type=Purchase.BOOST,
            content_type=self.comment_content_type,
            object_id=self.review_comment.id,
            created_date=today,
        )

        # Create distributions for fees
        for fee_type in ["BOUNTY_DAO_FEE", "BOUNTY_RH_FEE", "SUPPORT_RH_FEE"]:
            Distribution.objects.create(
                recipient=self.bank,
                giver=self.funder1,
                amount=50,
                distribution_type=fee_type,
                proof_item_content_type=self.purchase_content_type,
                proof_item_object_id=self.purchase.id,
                created_date=today,
            )

    def test_get_reviewers_leaderboard(self):
        """Test that reviewers endpoint returns correct data and ordering"""
        url = "/api/leaderboard/reviewers/"

        # Set date range to include our test data
        start_date = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        response = self.client.get(f"{url}?start_date={start_date}")

        self.assertEqual(response.status_code, 200)

        results = response.data["results"]
        self.assertTrue(len(results) > 0)

        # Check first reviewer (should be reviewer1 with highest earnings)
        top_reviewer = results[0]

        self.assertEqual(top_reviewer["id"], self.reviewer1.id)
        self.assertEqual(
            float(top_reviewer["earned_rsc"]), 150.0
        )  # 100 from bounty + 50 from tip
        self.assertEqual(float(top_reviewer["bounty_earnings"]), 100.0)
        self.assertEqual(float(top_reviewer["tip_earnings"]), 50.0)
        # Verify ordering
        if len(results) > 1:
            self.assertGreater(
                float(results[0]["earned_rsc"]), float(results[1]["earned_rsc"])
            )

    def test_get_funders_leaderboard(self):
        """
        Test the funders leaderboard endpoint.
        Tests all three types of funding:
        1. Purchase funding (FUNDRAISE_CONTRIBUTION and BOOST)
        2. Bounty funding (created bounties)
        3. Distribution funding (DAO fees, RH fees)
        """

        url = "/api/leaderboard/funders/"

        # Set date range to include yesterday
        today = timezone.now().date()
        yesterday_date = (today - timedelta(days=2)).strftime("%Y-%m-%d")
        tomorrow_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")

        response = self.client.get(
            f"{url}?start_date={yesterday_date}&end_date={tomorrow_date}"
        )
        self.assertEqual(response.status_code, 200)
        results = response.data["results"]

        top_funder = results[0]

        self.assertEqual(top_funder["id"], self.funder1.id)
        self.assertEqual(float(top_funder["purchase_funding"]), 300.0)  # 200 + 100
        self.assertEqual(float(top_funder["bounty_funding"]), 100.0)
        self.assertEqual(float(top_funder["distribution_funding"]), 150.0)  # 3 * 50
        self.assertEqual(float(top_funder["total_funding"]), 550.0)

    def test_get_leaderboard_overview(self):
        """
        Test the leaderboard overview endpoint.
        """

        Distribution.objects.create(
            recipient=self.reviewer1,
            giver=self.funder2,
            amount=500,
            distribution_type="PURCHASE",
            proof_item_content_type=self.purchase_content_type,
            proof_item_object_id=self.purchase.id,
        )

        url = "/api/leaderboard/overview/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("reviewers", response.data)
        self.assertIn("funders", response.data)

        # Get top reviewer and funder
        top_reviewer = response.data["reviewers"][0]
        top_funder = response.data["funders"][0]

        # Verify top reviewer data
        self.assertEqual(top_reviewer["id"], self.reviewer1.id)
        self.assertEqual(
            float(top_reviewer["earned_rsc"]), 650.0
        )  # 100 from bounty + 50 from tip + 500 from purchase
        self.assertEqual(float(top_reviewer["bounty_earnings"]), 100.0)
        self.assertEqual(float(top_reviewer["tip_earnings"]), 550.0)

        # Verify top funder data
        self.assertEqual(top_funder["id"], self.funder1.id)
        self.assertEqual(float(top_funder["total_funding"]), 550.0)  # 300 + 100 + 150
        self.assertEqual(float(top_funder["purchase_funding"]), 300.0)  # 200 + 100
        self.assertEqual(float(top_funder["bounty_funding"]), 100.0)
        self.assertEqual(float(top_funder["distribution_funding"]), 150.0)  # 3 * 50
