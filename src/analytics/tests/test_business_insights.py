import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase as UnitTestCase
from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from analytics.models import UserInteractions
from analytics.services.business_insights_service import (
    BusinessInsightsService,
    merge_previous_values,
)
from analytics.services.insights.endowment import get_endowment_metrics
from analytics.services.insights.expert_finder import get_expert_finder_metrics
from analytics.services.insights.funding import get_funding_metrics
from analytics.services.insights.pages import get_page_metrics
from analytics.services.insights.peer_reviews import get_peer_review_metrics
from analytics.services.insights.period import ReportPeriod, resolve_period
from analytics.services.insights.users import get_user_metrics
from analytics.services.insights.wac import get_contributor_metrics
from discussion.models import Vote
from purchase.models import (
    Balance,
    Fundraise,
    Grant,
    GrantApplication,
    Payment,
    Purchase,
)
from purchase.related_models.payment_model import PaymentProcessor, PaymentPurpose
from reputation.constants.bounty import ASSESSMENT_PERIOD_DAYS
from reputation.models import (
    Bounty,
    BountySolution,
    Escrow,
    StakingGlobalSnapshot,
    StakingUserSnapshot,
    StakingYieldRecord,
)
from research_ai.models import Expert, GeneratedEmail
from researchhub_comment.tests.helpers import create_rh_comment
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from review.models import Review
from user.models import UserVerification

User = get_user_model()


class ReportPeriodTests(UnitTestCase):
    def test_resolve_preset_period(self):
        # Arrange
        now = datetime(2026, 7, 20, 12, tzinfo=UTC)

        # Act
        period = resolve_period(period="7d", now=now)

        # Assert
        self.assertEqual(period.start, now - timedelta(days=7))
        self.assertEqual(period.end, now)
        self.assertEqual(period.label, "7d")

    def test_resolve_14d_preset_period(self):
        # Arrange
        now = datetime(2026, 7, 20, 12, tzinfo=UTC)

        # Act
        period = resolve_period(period="14d", now=now)

        # Assert
        self.assertEqual(period.start, now - timedelta(days=14))
        self.assertEqual(period.end, now)
        self.assertEqual(period.label, "14d")

    def test_previous_period_matches_same_length(self):
        # Arrange
        period = ReportPeriod(
            start=datetime(2026, 7, 14, tzinfo=UTC),
            end=datetime(2026, 7, 28, tzinfo=UTC),
            label="14d",
        )

        # Act
        previous = period.previous()

        # Assert
        self.assertEqual(previous.start, datetime(2026, 6, 30, tzinfo=UTC))
        self.assertEqual(previous.end, datetime(2026, 7, 14, tzinfo=UTC))
        self.assertEqual(previous.end - previous.start, period.end - period.start)

    def test_merge_previous_values_adds_numeric_siblings(self):
        # Arrange
        current = {
            "auto_drafted_proposals": 12,
            "funded": {"usd": Decimal(1200), "items": [{"id": 1}]},
            "label": "keep",
        }
        previous = {
            "auto_drafted_proposals": 8,
            "funded": {"usd": Decimal(900)},
        }

        # Act
        merged = merge_previous_values(current, previous)

        # Assert
        self.assertEqual(
            merged,
            {
                "auto_drafted_proposals": 12,
                "auto_drafted_proposals_previous": 8,
                "funded": {
                    "usd": Decimal(1200),
                    "usd_previous": Decimal(900),
                    "items": [{"id": 1}],
                },
                "label": "keep",
            },
        )

    def test_resolve_custom_period_uses_inclusive_end_date(self):
        # Arrange / Act
        period = resolve_period(
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 7),
        )

        # Assert
        self.assertEqual(period.start, datetime(2026, 7, 1, tzinfo=UTC))
        self.assertEqual(period.end, datetime(2026, 7, 8, tzinfo=UTC))
        self.assertEqual(period.label, "custom")

    def test_resolve_period_rejects_incomplete_custom_range(self):
        # Arrange / Act / Assert
        with self.assertRaisesRegex(
            ValueError,
            "start-date and end-date must be provided together",
        ):
            resolve_period(start_date=date(2026, 7, 1))

    def test_resolve_period_rejects_reversed_custom_range(self):
        # Arrange / Act / Assert
        with self.assertRaisesRegex(
            ValueError,
            "start-date must be before or equal to end-date",
        ):
            resolve_period(
                start_date=date(2026, 7, 8),
                end_date=date(2026, 7, 1),
            )


class BusinessInsightMetricTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.period = ReportPeriod(
            start=self.now - timedelta(days=7),
            end=self.now + timedelta(minutes=1),
            label="7d",
        )
        self.user = User.objects.create_user(
            username="insights-user",
            email="main@researchhub.foundation",
        )

    def test_funding_counts_grant_created_in_period(self):
        # Arrange
        post = create_post(created_by=self.user, document_type=GRANT)
        Grant.objects.create(
            created_by=self.user,
            unified_document=post.unified_document,
            amount=Decimal(1000),
            description="Test opportunity",
        )

        # Act
        metrics = get_funding_metrics(self.period)

        # Assert
        self.assertEqual(metrics["opportunities_created"], 1)

    def test_funding_splits_tied_independent_and_visibility(self):
        # Arrange
        applicant = User.objects.create_user(
            username="proposal-applicant",
            email="proposal-applicant@example.com",
        )
        grant_post = create_post(created_by=self.user, document_type=GRANT)
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_post.unified_document,
            amount=Decimal(1000),
            description="Test opportunity",
        )
        tied = create_post(
            created_by=applicant,
            document_type=PREREGISTRATION,
        )
        independent = create_post(
            created_by=applicant,
            document_type=PREREGISTRATION,
        )
        independent.unified_document.is_public = False
        independent.unified_document.save(update_fields=["is_public"])
        GrantApplication.objects.create(
            grant=grant,
            preregistration_post=tied,
            applicant=applicant,
        )

        # Act
        proposals = get_funding_metrics(self.period)["proposals"]

        # Assert
        self.assertEqual(proposals["submitted"], 2)
        self.assertEqual(proposals["tied_to_opportunity"], 1)
        self.assertEqual(proposals["independent"], 1)
        self.assertEqual(
            proposals["independent"] + proposals["tied_to_opportunity"],
            proposals["submitted"],
        )
        self.assertEqual(proposals["public"], 1)
        self.assertEqual(proposals["private"], 1)

    def test_funding_tied_only_counts_proposals_created_in_period(self):
        # Arrange: application in period for an older proposal should not count.
        applicant = User.objects.create_user(
            username="old-proposal-applicant",
            email="old-proposal-applicant@example.com",
        )
        grant_post = create_post(created_by=self.user, document_type=GRANT)
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_post.unified_document,
            amount=Decimal(1000),
            description="Test opportunity",
        )
        old_proposal = create_post(
            created_by=applicant,
            document_type=PREREGISTRATION,
        )
        old_proposal.created_date = self.period.start - timedelta(days=30)
        old_proposal.save(update_fields=["created_date"])
        GrantApplication.objects.create(
            grant=grant,
            preregistration_post=old_proposal,
            applicant=applicant,
        )

        # Act
        proposals = get_funding_metrics(self.period)["proposals"]

        # Assert
        self.assertEqual(proposals["submitted"], 0)
        self.assertEqual(proposals["tied_to_opportunity"], 0)
        self.assertEqual(proposals["independent"], 0)

    def test_funding_classifies_credit_contribution_without_fees(self):
        # Arrange
        post = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
        )
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=post.unified_document,
            goal_amount=Decimal(1000),
        )
        fundraise_content_type = ContentType.objects.get_for_model(Fundraise)
        purchase = Purchase.objects.create(
            user=self.user,
            content_type=fundraise_content_type,
            object_id=fundraise.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            amount="100",
            rsc_usd_rate=2,
            paid_status=Purchase.PAID,
        )
        purchase_content_type = ContentType.objects.get_for_model(Purchase)
        Balance.objects.create(
            user=self.user,
            content_type=purchase_content_type,
            object_id=purchase.id,
            purchase=purchase,
            amount="-100",
            is_locked=True,
            lock_type=Balance.LockType.FUNDING_CREDIT,
        )
        Balance.objects.create(
            user=self.user,
            content_type=fundraise_content_type,
            object_id=fundraise.id,
            purchase=purchase,
            amount="-9",
            is_locked=True,
            lock_type=Balance.LockType.FUNDING_CREDIT,
        )
        Payment.objects.create(
            amount=17684,
            currency="USD",
            external_payment_id="pi_business_insights",
            payment_processor=PaymentProcessor.STRIPE,
            purpose=PaymentPurpose.RSC_PURCHASE,
            content_type=ContentType.objects.get_for_model(User),
            object_id=self.user.id,
            user=self.user,
        )

        # Act
        funded = get_funding_metrics(self.period)["funded"]

        # Assert
        self.assertEqual(
            funded["payment_methods"],
            {
                "rsc": Decimal(0),
                "cc_via_stripe": Decimal("176.84"),
                "daf": Decimal(0),
                "funding_credits": Decimal(100),
                "promotional_credits": Decimal(0),
            },
        )

    def test_pages_returns_top_documents(self):
        # Arrange
        post = create_post(created_by=self.user)
        post.slug = "top-page-slug"
        post.preview_img = "https://example.com/preview.png"
        post.save(update_fields=["slug", "preview_img"])
        UserInteractions.objects.create(
            user=self.user,
            external_user_id="insights-user",
            event="PAGE_VIEW",
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            event_timestamp=self.now,
        )

        # Act
        metrics = get_page_metrics(self.period)

        # Assert
        self.assertEqual(len(metrics["top_documents"]), 1)
        top = metrics["top_documents"][0]
        self.assertEqual(top["document_id"], post.unified_document_id)
        self.assertEqual(top["document_type"], post.unified_document.document_type)
        self.assertEqual(top["views"], 1)
        self.assertEqual(top["paper_id"], None)
        self.assertEqual(top["post_id"], post.id)
        self.assertEqual(top["slug"], "top-page-slug")
        self.assertEqual(top["preview_img"], "https://example.com/preview.png")
        self.assertEqual(top["url"], post.unified_document.frontend_view_link())

    def test_expert_finder_counts_registered_invited_experts(self):
        # Arrange
        expert = Expert.objects.create(email="expert@example.com")
        GeneratedEmail.objects.create(
            created_by=self.user,
            expert_email="expert@example.com",
            template="collaboration",
            status=GeneratedEmail.Status.SENT,
            channels=[GeneratedEmail.Channel.EMAIL],
        )
        GeneratedEmail.objects.create(
            created_by=self.user,
            expert_email="linkedin-expert@example.com",
            template="collaboration",
            status=GeneratedEmail.Status.SENT,
            channels=[GeneratedEmail.Channel.LINKEDIN],
        )
        invited_user = User.objects.create_user(
            username="invited-expert",
            email="expert@example.com",
        )
        expert.registered_user = invited_user
        expert.save(update_fields=["registered_user"])

        # Act
        metrics = get_expert_finder_metrics(self.period)

        # Assert
        self.assertEqual(
            metrics,
            {
                "experts_generated_outreach_for": 2,
                "invited_experts": 1,
                "auto_drafted_proposals": 0,
                "outreach_by_channel": {
                    "email": 1,
                    "linkedin": 1,
                    "x": 0,
                },
            },
        )

    def test_endowment_returns_latest_snapshot(self):
        # Arrange
        snapshot = StakingGlobalSnapshot.objects.create(
            accrual_date=self.now.date(),
            total_staked=Decimal("123.45"),
        )
        user_snapshot = StakingUserSnapshot.objects.create(
            global_snapshot=snapshot,
            user=self.user,
            stake_amount=Decimal("123.45"),
        )
        StakingYieldRecord.objects.create(
            user_snapshot=user_snapshot,
            yield_amount=Decimal("1.23"),
        )

        # Act
        metrics = get_endowment_metrics(self.period)

        # Assert
        self.assertEqual(metrics["tvl_rsc"], Decimal("123.45"))
        self.assertEqual(metrics["as_of"], self.now.date())
        self.assertGreater(metrics["current_yield_apy_percent"], 0)
        self.assertEqual(metrics["unique_earners"], 1)

    def test_peer_reviews_counts_tip_after_bounty_expiry(self):
        # Arrange: bounty expired; RHF tip still assesses the review.
        post = create_post(created_by=self.user)
        post_content_type = ContentType.objects.get_for_model(post)
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            content_type=post_content_type,
            object_id=post.id,
        )
        assessment_start = self.now - timedelta(days=13)
        bounty = Bounty.objects.create(
            created_by=self.user,
            item_content_type=post_content_type,
            item_object_id=post.id,
            unified_document=post.unified_document,
            escrow=escrow,
            amount=Decimal(100),
            bounty_type=Bounty.Type.REVIEW,
            status=Bounty.EXPIRED,
            assessment_end_date=assessment_start
            + timedelta(days=ASSESSMENT_PERIOD_DAYS),
            expiration_date=self.now - timedelta(days=3),
        )
        reviewer = User.objects.create_user(
            username="assessed-reviewer",
            email="assessed-reviewer@example.com",
        )
        comment = create_rh_comment(post=post, created_by=reviewer)
        comment.comment_type = "REVIEW"
        comment.save(update_fields=["comment_type"])
        comment_content_type = ContentType.objects.get_for_model(comment)
        Review.objects.create(
            created_by=reviewer,
            content_type=comment_content_type,
            object_id=comment.id,
            unified_document=post.unified_document,
            is_assessed=True,
        )
        BountySolution.objects.create(
            bounty=bounty,
            status=BountySolution.Status.SUBMITTED,
            created_by=reviewer,
            content_type=comment_content_type,
            object_id=comment.id,
        )
        Purchase.objects.create(
            user=self.user,
            content_type=comment_content_type,
            object_id=comment.id,
            purchase_type=Purchase.BOOST,
            purchase_method=Purchase.OFF_CHAIN,
            paid_status=Purchase.PAID,
            amount=10,
        )

        # Act
        metrics = get_peer_review_metrics(self.period)

        # Assert
        self.assertEqual(metrics["assessed_reviews"], 1)
        self.assertEqual(metrics["avg_review_assessment_days"], 13)

    def test_peer_reviews_ignores_ai_reviews(self):
        # Arrange
        from user.related_models.user_model import AI_EXPERT_EMAIL

        ai_user = User.objects.create_user(
            username="ai-reviewer",
            email=AI_EXPERT_EMAIL,
        )
        post = create_post(created_by=self.user)
        comment = create_rh_comment(post=post, created_by=ai_user)
        comment.comment_type = "REVIEW"
        comment.save(update_fields=["comment_type"])
        comment_content_type = ContentType.objects.get_for_model(comment)
        Review.objects.create(
            created_by=ai_user,
            content_type=comment_content_type,
            object_id=comment.id,
            unified_document=post.unified_document,
            is_assessed=True,
        )
        Purchase.objects.create(
            user=self.user,
            content_type=comment_content_type,
            object_id=comment.id,
            purchase_type=Purchase.BOOST,
            purchase_method=Purchase.OFF_CHAIN,
            paid_status=Purchase.PAID,
            amount=10,
        )

        # Act
        metrics = get_peer_review_metrics(self.period)

        # Assert
        self.assertEqual(metrics["submitted_reviews"], 0)
        self.assertEqual(metrics["assessed_reviews"], 0)
        self.assertIsNone(metrics["avg_review_assessment_days"])

    def test_wac_counts_active_and_verified_user(self):
        # Arrange
        post = create_post(created_by=self.user)
        Vote.objects.create(
            created_by=self.user,
            item=post,
            vote_type=Vote.UPVOTE,
        )
        UserVerification.objects.create(
            user=self.user,
            first_name="Insight",
            last_name="User",
            status=UserVerification.Status.APPROVED,
            verified_by=UserVerification.Type.MANUAL,
            external_id="manual-insights-user",
        )
        inactive_user = User.objects.create_user(
            username="verified-but-inactive",
            email="verified-but-inactive@example.com",
        )
        UserVerification.objects.create(
            user=inactive_user,
            first_name="Inactive",
            last_name="User",
            status=UserVerification.Status.APPROVED,
            verified_by=UserVerification.Type.MANUAL,
            external_id="manual-inactive-user",
        )

        # Act
        metrics = get_contributor_metrics(self.period)

        # Assert
        self.assertEqual(metrics["wac"]["count"], 1)
        self.assertEqual(metrics["verified_wac"]["count"], 1)

    def test_users_split_email_and_google_signups(self):
        # Arrange
        EmailAddress.objects.create(
            user=self.user,
            email=self.user.email,
            primary=True,
            verified=True,
        )
        UserVerification.objects.create(
            user=self.user,
            first_name="Insight",
            last_name="User",
            status=UserVerification.Status.APPROVED,
            verified_by=UserVerification.Type.MANUAL,
            external_id="manual-user-metrics",
        )
        google_user = User.objects.create_user(
            username="google-signup",
            email="google-signup@example.com",
        )
        SocialAccount.objects.create(
            user=google_user,
            provider="google",
            uid="google-signup",
        )
        SocialAccount.objects.create(
            user=self.user,
            provider="orcid",
            uid="0000-0001-2345-6789",
        )

        # Act
        metrics = get_user_metrics(self.period)

        # Assert
        self.assertEqual(metrics["verified_users"], 1)
        self.assertEqual(metrics["orcid_connected"], 1)
        self.assertEqual(
            metrics["newly_created"],
            {
                "total": 2,
                "via_email": {
                    "total": 1,
                    "verified_email": 1,
                },
                "via_google": 1,
            },
        )

    def test_business_insights_includes_previous_period_values(self):
        # Arrange: one opportunity created in the current window, none before.
        post = create_post(created_by=self.user, document_type=GRANT)
        Grant.objects.create(
            created_by=self.user,
            unified_document=post.unified_document,
            amount=Decimal(1000),
            description="Current-period opportunity",
        )
        service = BusinessInsightsService(self.period)

        # Act
        report = service.build()

        # Assert
        self.assertEqual(report["period"]["previous_end"], self.period.start)
        self.assertEqual(
            report["period"]["previous_start"],
            self.period.start - (self.period.end - self.period.start),
        )
        self.assertEqual(report["funding"]["opportunities_created"], 1)
        self.assertEqual(report["funding"]["opportunities_created_previous"], 0)
        self.assertNotIn("top_documents_previous", report["pages"])
        self.assertIn("top_documents", report["pages"])


class ReportBusinessInsightsCommandTests(TestCase):
    @patch(
        "analytics.management.commands.report_business_insights."
        "BusinessInsightsService.build"
    )
    def test_command_outputs_valid_json(self, build_report):
        # Arrange
        build_report.return_value = {
            "period": {"label": "7d"},
            "funding": {
                "zero": Decimal("0E-10"),
                "amount": Decimal("125.25"),
            },
        }
        stdout = StringIO()

        # Act
        call_command("report_business_insights", period="7d", stdout=stdout)
        output = json.loads(stdout.getvalue())

        # Assert
        self.assertEqual(output["period"]["label"], "7d")
        self.assertIn("funding", output)
        self.assertEqual(output["funding"]["zero"], 0)
        self.assertEqual(output["funding"]["amount"], 125.25)

    @patch(
        "analytics.management.commands.report_business_insights."
        "BusinessInsightsService.build"
    )
    def test_command_writes_json_to_output_file(self, build_report):
        # Arrange
        build_report.return_value = {
            "period": {"label": "7d"},
            "funding": {},
        }
        stdout = StringIO()
        stderr = StringIO()

        with TemporaryDirectory() as directory:
            output_path = Path(directory) / "reports" / "insights.json"

            # Act
            call_command(
                "report_business_insights",
                period="7d",
                output=output_path,
                pretty=True,
                stdout=stdout,
                stderr=stderr,
            )
            output = json.loads(output_path.read_text(encoding="utf-8"))
            console_output = json.loads(stdout.getvalue())

            # Assert
            self.assertEqual(output["period"]["label"], "7d")
            self.assertEqual(console_output, output)
            self.assertIn(str(output_path), stderr.getvalue())
