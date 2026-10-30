from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework.test import APITestCase

from paper.related_models.paper_model import Paper
from purchase.models import Purchase
from reputation.models import Bounty, BountySolution, Distribution
from reputation.related_models.escrow import Escrow, EscrowRecipients
from researchhub_comment.constants.rh_comment_thread_types import (
    ANSWER,
    COMMUNITY_REVIEW,
    PEER_REVIEW,
)
from researchhub_comment.models import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from user.related_models.funding_activity_model import (
    FundingActivity,
    FundingActivityRecipient,
)
from user.related_models.leaderboard_model import Leaderboard
from user.tests.helpers import create_user


class LeaderboardApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Create test users
        cls.reviewer1 = create_user(
            email="reviewer1@researchhub.com", first_name="First", last_name="Reviewer"
        )
        cls.reviewer2 = create_user(
            email="reviewer2@researchhub.com", first_name="Second", last_name="Reviewer"
        )

        cls.funder1 = create_user(
            email="funder1@researchhub.com", first_name="First", last_name="Funder"
        )

        cls.funder2 = create_user(
            email="funder2@researchhub.com", first_name="Second", last_name="Funder"
        )

        cls.bank = create_user(
            email="bank@researchhub.com", first_name="Bank", last_name="Bank"
        )

        # Create a paper for the review
        cls.paper = Paper.objects.create(title="Test Paper")

        # Create thread properly linked to the paper
        cls.paper_content_type = ContentType.objects.get_for_model(Paper)
        cls.thread = RhCommentThreadModel.objects.create(
            thread_type=PEER_REVIEW,
            content_type=cls.paper_content_type,
            object_id=cls.paper.id,
            created_by=cls.funder1,
        )

        # Create peer review comment
        cls.review_comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "Test review"}]},
            comment_type=PEER_REVIEW,
            created_by=cls.reviewer1,
            thread=cls.thread,
        )

        # Store content types we'll need
        cls.comment_content_type = ContentType.objects.get_for_model(RhCommentModel)
        cls.purchase_content_type = ContentType.objects.get_for_model(Purchase)

        # Create escrow first, linked to the review comment
        cls.escrow = Escrow.objects.create(
            hold_type=Escrow.BOUNTY,
            status=Escrow.PAID,
            amount_holding=100,
            content_type=cls.comment_content_type,
            object_id=cls.review_comment.id,
            created_by=cls.funder1,
        )

        # Then create bounty with escrow reference and unified_document
        cls.bounty = Bounty.objects.create(
            bounty_type=Bounty.Type.REVIEW,
            amount=100,
            created_by=cls.funder1,
            item_content_type=cls.comment_content_type,
            item_object_id=cls.review_comment.id,
            escrow=cls.escrow,
            unified_document=cls.paper.unified_document,
        )

        # Create escrow recipient for reviewer1
        EscrowRecipients.objects.create(
            escrow=cls.escrow, user=cls.reviewer1, amount=100
        )

        # Create a purchase/tip for reviewer1
        cls.purchase = Purchase.objects.create(
            user=cls.funder1,
            amount="50",
            paid_status=Purchase.PAID,
            content_type=cls.comment_content_type,
            object_id=cls.review_comment.id,
        )

        # Create distribution (tip) for reviewer1
        Distribution.objects.create(
            recipient=cls.reviewer1,
            giver=cls.funder1,
            amount=50,
            distribution_type="PURCHASE",
            proof_item_content_type=cls.purchase_content_type,
            proof_item_object_id=cls.purchase.id,
        )

        # Create bounty solution linking the bounty to the review comment
        cls.bounty_solution = BountySolution.objects.create(
            bounty=cls.bounty,
            created_by=cls.reviewer1,
            content_type=cls.comment_content_type,
            object_id=cls.review_comment.id,
        )

        today = timezone.now()

        # Create fundraise purchase
        Purchase.objects.create(
            user=cls.funder1,
            amount="200",
            paid_status=Purchase.PAID,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            content_type=cls.comment_content_type,
            object_id=cls.review_comment.id,
            created_date=today,
        )

        # Create boost purchase
        Purchase.objects.create(
            user=cls.funder1,
            amount="100",
            paid_status=Purchase.PAID,
            purchase_type=Purchase.BOOST,
            content_type=cls.comment_content_type,
            object_id=cls.review_comment.id,
            created_date=today,
        )

        # Create distributions for fees
        for fee_type in ["BOUNTY_DAO_FEE", "BOUNTY_RH_FEE", "SUPPORT_RH_FEE"]:
            Distribution.objects.create(
                recipient=cls.bank,
                giver=cls.funder1,
                amount=50,
                distribution_type=fee_type,
                proof_item_content_type=cls.purchase_content_type,
                proof_item_object_id=cls.purchase.id,
                created_date=today,
            )

        cls.regular_review_thread = RhCommentThreadModel.objects.create(
            thread_type=COMMUNITY_REVIEW,
            content_type=cls.paper_content_type,
            object_id=cls.paper.id,
            created_by=cls.funder1,
        )

        cls.regular_review_comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "Test regular review"}]},
            comment_type=COMMUNITY_REVIEW,
            created_by=cls.reviewer1,
            thread=cls.regular_review_thread,
        )

        cls.answer_comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "Test answer"}]},
            comment_type=ANSWER,
            created_by=cls.reviewer1,
            thread=cls.regular_review_thread,
        )

        # Create escrow for regular review
        cls.regular_review_escrow = Escrow.objects.create(
            hold_type=Escrow.BOUNTY,
            status=Escrow.PAID,
            amount_holding=75,
            content_type=cls.comment_content_type,
            object_id=cls.regular_review_comment.id,
            created_by=cls.funder1,
        )

        # Create bounty for regular review
        cls.regular_review_bounty = Bounty.objects.create(
            bounty_type=Bounty.Type.REVIEW,
            amount=75,
            created_by=cls.funder1,
            item_content_type=cls.comment_content_type,
            item_object_id=cls.regular_review_comment.id,
            escrow=cls.regular_review_escrow,
            unified_document=cls.paper.unified_document,
        )

        # Create escrow recipient for regular review
        EscrowRecipients.objects.create(
            escrow=cls.regular_review_escrow, user=cls.reviewer1, amount=75
        )

        # Create bounty solution for regular review
        cls.regular_review_bounty_solution = BountySolution.objects.create(
            bounty=cls.regular_review_bounty,
            created_by=cls.reviewer1,
            content_type=cls.comment_content_type,
            object_id=cls.regular_review_comment.id,
        )

        # Create a purchase/tip for regular review
        cls.regular_review_purchase = Purchase.objects.create(
            user=cls.funder1,
            amount="25",
            paid_status=Purchase.PAID,
            purchase_type=Purchase.BOOST,
            content_type=cls.comment_content_type,
            object_id=cls.regular_review_comment.id,
            created_date=today,
        )

        # Create distribution (tip) for regular review
        Distribution.objects.create(
            recipient=cls.reviewer1,
            giver=cls.funder1,
            amount=25,
            distribution_type="PURCHASE",
            proof_item_content_type=cls.purchase_content_type,
            proof_item_object_id=cls.regular_review_purchase.id,
        )

        cls.now = timezone.now()
        ud = cls.paper.unified_document
        ct_user = ContentType.objects.get_for_model(type(cls.reviewer1))
        sid = 2000

        def make_activity(funder, source_type, total_amount, **kwargs):
            nonlocal sid
            sid += 1
            fa = FundingActivity.objects.create(
                funder=funder,
                source_type=source_type,
                total_amount=Decimal(str(total_amount)),
                unified_document=ud,
                activity_date=cls.now,
                source_content_type=ct_user,
                source_object_id=sid,
                **kwargs,
            )
            return fa

        # Reviewer1 earnings: bounty 100 + 75, tip 50 + 25
        for amount in (100, 75):
            fa = make_activity(cls.funder1, FundingActivity.BOUNTY_PAYOUT, amount)
            FundingActivityRecipient.objects.create(
                activity=fa, recipient_user=cls.reviewer1, amount=Decimal(str(amount))
            )
        for amount in (50, 25):
            fa = make_activity(cls.funder1, FundingActivity.TIP_REVIEW, amount)
            FundingActivityRecipient.objects.create(
                activity=fa, recipient_user=cls.reviewer1, amount=Decimal(str(amount))
            )

        # Funder1: purchase 200 + 100 + 25, fees 50 * 3 (bounty 100+75 already above)
        for amount in (200, 100, 25):
            make_activity(
                cls.funder1,
                (
                    FundingActivity.FUNDRAISE_PAYOUT
                    if amount == 200
                    else FundingActivity.TIP_DOCUMENT
                ),
                amount,
            )
        for _ in range(3):
            make_activity(cls.funder1, FundingActivity.FEE, 50)

        # Pre-computed leaderboard entries
        Leaderboard.objects.create(
            user=cls.reviewer1,
            leaderboard_type=Leaderboard.EARNER,
            period=Leaderboard.ALL_TIME,
            rank=1,
            total_amount=Decimal(250),
        )
        Leaderboard.objects.create(
            user=cls.funder1,
            leaderboard_type=Leaderboard.FUNDER,
            period=Leaderboard.ALL_TIME,
            rank=1,
            total_amount=Decimal(650),
        )
        Leaderboard.objects.create(
            user=cls.reviewer1,
            leaderboard_type=Leaderboard.EARNER,
            period=Leaderboard.SEVEN_DAYS,
            rank=1,
            total_amount=Decimal(250),
        )
        Leaderboard.objects.create(
            user=cls.funder1,
            leaderboard_type=Leaderboard.FUNDER,
            period=Leaderboard.THIRTY_DAYS,
            rank=1,
            total_amount=Decimal(650),
        )

    def test_get_reviewers_leaderboard(self):
        """Test that reviewers endpoint returns correct data (from FundingActivity)."""
        url = "/api/leaderboard/reviewers/"

        start_date = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        end_date = (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        response = self.client.get(
            f"{url}?start_date={start_date}&end_date={end_date}&page_size=500"
        )

        self.assertEqual(response.status_code, 200)

        results = response.data["results"]
        self.assertTrue(len(results) > 0)

        reviewer1_entry = next(
            (r for r in results if r["id"] == self.reviewer1.id), None
        )
        self.assertIsNotNone(reviewer1_entry)
        self.assertEqual(float(reviewer1_entry["earned_rsc"]), 250.0)
        self.assertIn("is_verified", reviewer1_entry)
        self.assertIn("rank", reviewer1_entry)
        self.assertEqual(reviewer1_entry["rank"], 1)

        for i in range(len(results) - 1):
            self.assertGreaterEqual(
                float(results[i]["earned_rsc"]),
                float(results[i + 1]["earned_rsc"]),
            )
            self.assertIn("rank", results[i])
            self.assertIn("rank", results[i + 1])
            self.assertEqual(results[i]["rank"], i + 1)
            self.assertEqual(results[i + 1]["rank"], i + 2)

    def test_get_funders_leaderboard(self):
        """Test the funders leaderboard endpoint (total from FundingActivity)."""
        url = "/api/leaderboard/funders/"

        today = timezone.now().date()
        yesterday_date = (today - timedelta(days=2)).strftime("%Y-%m-%d")
        tomorrow_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        response = self.client.get(
            f"{url}?start_date={yesterday_date}&end_date={tomorrow_date}&page_size=500"
        )
        self.assertEqual(response.status_code, 200)
        results = response.data["results"]

        funder1_entry = next((r for r in results if r["id"] == self.funder1.id), None)
        self.assertIsNotNone(funder1_entry)
        self.assertEqual(float(funder1_entry["total_funding"]), 725.0)
        self.assertIn("is_verified", funder1_entry)
        self.assertIn("rank", funder1_entry)
        self.assertEqual(funder1_entry["rank"], 1)

    def test_get_leaderboard_overview(self):
        """Test the leaderboard overview endpoint (uses Leaderboard table only)."""
        url = "/api/leaderboard/overview/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("reviewers", response.data)
        self.assertIn("funders", response.data)

        top_reviewer = response.data["reviewers"][0]
        top_funder = response.data["funders"][0]

        self.assertEqual(top_reviewer["id"], self.reviewer1.id)
        self.assertEqual(float(top_reviewer["earned_rsc"]), 250.0)
        self.assertIn("is_verified", top_reviewer)
        self.assertIn("rank", top_reviewer)
        self.assertEqual(top_reviewer["rank"], 1)

        self.assertEqual(top_funder["id"], self.funder1.id)
        self.assertEqual(float(top_funder["total_funding"]), 650.0)
        self.assertIn("is_verified", top_funder)
        self.assertIn("rank", top_funder)
        self.assertEqual(top_funder["rank"], 1)

    def test_date_range_exceeds_max_days_reviewers(self):
        """Test that date range exceeding 60 days returns 400."""
        url = "/api/leaderboard/reviewers/"
        response = self.client.get(f"{url}?start_date=2025-01-01&end_date=2025-03-15")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "Date range exceeds 60 days")

    def test_date_range_exceeds_max_days_funders(self):
        """Test that date range exceeding 60 days returns 400."""
        url = "/api/leaderboard/funders/"
        response = self.client.get(f"{url}?start_date=2025-01-01&end_date=2025-03-15")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "Date range exceeds 60 days")

    def test_date_range_funders_excludes_bank(self):
        """
        Excluded users (e.g. bank) do not appear in funders leaderboard by date range.
        """
        ct_user = ContentType.objects.get_for_model(type(self.reviewer1))
        FundingActivity.objects.create(
            funder=self.bank,
            source_type=FundingActivity.FEE,
            total_amount=Decimal(999),
            unified_document=self.paper.unified_document,
            activity_date=timezone.now(),
            source_content_type=ct_user,
            source_object_id=9999,
        )
        start_date = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        end_date = (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        url = f"/api/leaderboard/funders/?start_date={start_date}&end_date={end_date}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        user_ids = [r["id"] for r in response.data["results"]]
        self.assertNotIn(self.bank.id, user_ids)
        self.assertIn(self.funder1.id, user_ids)

    def test_date_range_reviewers_excludes_bank(self):
        """
        Excluded users (e.g. bank) do not appear in reviewers leaderboard by date range.
        """
        ct_user = ContentType.objects.get_for_model(type(self.reviewer1))
        fa = FundingActivity.objects.create(
            funder=self.funder1,
            source_type=FundingActivity.TIP_REVIEW,
            total_amount=Decimal(500),
            unified_document=self.paper.unified_document,
            activity_date=timezone.now(),
            source_content_type=ct_user,
            source_object_id=8888,
        )
        FundingActivityRecipient.objects.create(
            activity=fa, recipient_user=self.bank, amount=Decimal(500)
        )
        start_date = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        end_date = (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        url = f"/api/leaderboard/reviewers/?start_date={start_date}&end_date={end_date}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        user_ids = [r["id"] for r in response.data["results"]]
        self.assertNotIn(self.bank.id, user_ids)
        self.assertIn(self.reviewer1.id, user_ids)

    def test_reviewers_leaderboard_includes_rank(self):
        """Test that reviewers endpoint includes rank field."""
        url = "/api/leaderboard/reviewers/"
        start_date = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        end_date = (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        response = self.client.get(
            f"{url}?start_date={start_date}&end_date={end_date}&page_size=500"
        )

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertTrue(len(results) > 0)

        for i, entry in enumerate(results):
            self.assertIn("rank", entry)
            self.assertEqual(entry["rank"], i + 1)

    def test_funders_leaderboard_includes_rank(self):
        """Test that funders endpoint includes rank field."""
        url = "/api/leaderboard/funders/"
        start_date = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        end_date = (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        response = self.client.get(
            f"{url}?start_date={start_date}&end_date={end_date}&page_size=500"
        )

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertTrue(len(results) > 0)

        for i, entry in enumerate(results):
            self.assertIn("rank", entry)
            self.assertEqual(entry["rank"], i + 1)

    def test_leaderboard_me_requires_auth(self):
        """Test that GET /leaderboard/me/ returns 401 when not authenticated."""
        url = "/api/leaderboard/me/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_leaderboard_me_reviewer_date_range(self):
        """Test /leaderboard/me/ returns current user reviewer data for date range."""
        url = "/api/leaderboard/me/"
        start_date = (self.now - timedelta(days=2)).strftime("%Y-%m-%d")
        end_date = (self.now + timedelta(days=2)).strftime("%Y-%m-%d")

        self.client.force_authenticate(user=self.reviewer1)
        response = self.client.get(f"{url}?start_date={start_date}&end_date={end_date}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("reviewer", response.data)
        self.assertIn("funder", response.data)
        reviewer = response.data["reviewer"]
        self.assertIsNotNone(reviewer)
        self.assertEqual(reviewer["id"], self.reviewer1.id)
        self.assertIn("rank", reviewer)
        self.assertIn("earned_rsc", reviewer)
        self.assertEqual(float(reviewer["earned_rsc"]), 250.0)
        self.assertEqual(reviewer["rank"], 1)

    def test_leaderboard_me_funder_date_range(self):
        """Test /leaderboard/me/ returns current user funder data for date range."""
        url = "/api/leaderboard/me/"
        start_date = (self.now - timedelta(days=2)).strftime("%Y-%m-%d")
        end_date = (self.now + timedelta(days=2)).strftime("%Y-%m-%d")

        self.client.force_authenticate(user=self.funder1)
        response = self.client.get(f"{url}?start_date={start_date}&end_date={end_date}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("reviewer", response.data)
        self.assertIn("funder", response.data)
        funder = response.data["funder"]
        self.assertIsNotNone(funder)
        self.assertEqual(funder["id"], self.funder1.id)
        self.assertIn("rank", funder)
        self.assertIn("total_funding", funder)
        self.assertEqual(float(funder["total_funding"]), 725.0)
        self.assertEqual(funder["rank"], 1)

    def test_reviewers_leaderboard_precomputed_period_includes_rank(self):
        """Test that reviewers endpoint with pre-computed period includes rank."""
        url = "/api/leaderboard/reviewers/"
        response = self.client.get(f"{url}?period=7_days")

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertTrue(len(results) > 0)

        for entry in results:
            self.assertIn("rank", entry)

        reviewer1_entry = next(
            (r for r in results if r["id"] == self.reviewer1.id), None
        )
        if reviewer1_entry:
            self.assertEqual(reviewer1_entry["rank"], 1)

    def test_funders_leaderboard_precomputed_period_includes_rank(self):
        """Test that funders endpoint with pre-computed period includes rank."""
        url = "/api/leaderboard/funders/"
        response = self.client.get(f"{url}?period=30_days")

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertTrue(len(results) > 0)

        for entry in results:
            self.assertIn("rank", entry)

        funder1_entry = next((r for r in results if r["id"] == self.funder1.id), None)
        if funder1_entry:
            self.assertEqual(funder1_entry["rank"], 1)

    def test_leaderboard_me_reviewer_precomputed_period(self):
        """
        Test /leaderboard/me/ with period=7_days returns reviewer data from Leaderboard.
        """
        url = "/api/leaderboard/me/"
        self.client.force_authenticate(user=self.reviewer1)
        response = self.client.get(f"{url}?period=7_days")

        self.assertEqual(response.status_code, 200)
        self.assertIn("reviewer", response.data)
        self.assertIn("funder", response.data)
        reviewer = response.data["reviewer"]
        self.assertIsNotNone(reviewer)
        self.assertEqual(reviewer["id"], self.reviewer1.id)
        self.assertEqual(reviewer["rank"], 1)
        self.assertEqual(float(reviewer["earned_rsc"]), 250.0)

    def test_leaderboard_me_funder_precomputed_period(self):
        """
        Test /leaderboard/me/ with period=30_days returns funder data from Leaderboard.
        """
        url = "/api/leaderboard/me/"
        self.client.force_authenticate(user=self.funder1)
        response = self.client.get(f"{url}?period=30_days")

        self.assertEqual(response.status_code, 200)
        self.assertIn("reviewer", response.data)
        self.assertIn("funder", response.data)
        funder = response.data["funder"]
        self.assertIsNotNone(funder)
        self.assertEqual(funder["id"], self.funder1.id)
        self.assertEqual(funder["rank"], 1)
        self.assertEqual(float(funder["total_funding"]), 650.0)

    def test_leaderboard_me_default_all_time(self):
        """
        Test /leaderboard/me/ with no params defaults to all_time (overview-style).
        """
        url = "/api/leaderboard/me/"
        self.client.force_authenticate(user=self.reviewer1)
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("reviewer", response.data)
        self.assertIn("funder", response.data)
        reviewer = response.data["reviewer"]
        self.assertIsNotNone(reviewer)
        self.assertEqual(reviewer["id"], self.reviewer1.id)
        self.assertIn("rank", reviewer)
        self.assertIn("earned_rsc", reviewer)
