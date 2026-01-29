import uuid
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from funding_dashboard.services import DashboardService
from hub.models import Hub
from organizations.models import NonprofitFundraiseLink, NonprofitOrg
from purchase.models import Fundraise, Grant, GrantApplication, Purchase, UsdFundraiseContribution
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import GRANT, PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.models import User


class BaseDashboardTest(TestCase):
    """Base test class with helper methods for dashboard service tests."""

    def setUp(self) -> None:
        self.funder = User.objects.create_user(
            username="funder", email="funder@test.com", password=uuid.uuid4().hex
        )
        self.other_user = User.objects.create_user(
            username="other", email="other@test.com", password=uuid.uuid4().hex
        )
        self.author = User.objects.create_user(
            username="author", email="author@test.com", password=uuid.uuid4().hex
        )
        self.hub = Hub.objects.create(name="Test Hub")
        self.hub2 = Hub.objects.create(name="Second Hub")
        self.service = DashboardService(self.funder)
        self.fundraise_ct = ContentType.objects.get_for_model(Fundraise)
        RscExchangeRate.objects.create(rate=1.0, real_rate=1.0)

    def _create_grant(self, creator: User, status: str = Grant.OPEN) -> Grant:
        doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        doc.hubs.add(self.hub)
        ResearchhubPost.objects.create(
            created_by=creator, document_type=GRANT, unified_document=doc
        )
        return Grant.objects.create(
            created_by=creator,
            unified_document=doc,
            amount=Decimal("10000"),
            description="Test grant",
            status=status,
        )

    def _create_fundraise(
        self, creator: User, status: str = Fundraise.OPEN, hubs: list[Hub] | None = None
    ) -> tuple[Fundraise, ResearchhubPost]:
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PREREGISTRATION)
        for hub in hubs or [self.hub]:
            doc.hubs.add(hub)
        post = ResearchhubPost.objects.create(
            created_by=creator, document_type=PREREGISTRATION, unified_document=doc
        )
        fundraise = Fundraise.objects.create(
            created_by=creator,
            unified_document=doc,
            goal_amount=10000,
            status=status,
        )
        return fundraise, post

    def _apply_to_grant(
        self, grant: Grant, applicant: User, post: ResearchhubPost
    ) -> GrantApplication:
        return GrantApplication.objects.create(
            grant=grant, applicant=applicant, preregistration_post=post
        )

    def _contribute_rsc(self, user: User, fundraise: Fundraise, amount: str) -> Purchase:
        return Purchase.objects.create(
            user=user,
            content_type=self.fundraise_ct,
            object_id=fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            purchase_method=Purchase.OFF_CHAIN,
            paid_status=Purchase.PAID,
            amount=amount,
        )

    def _contribute_usd(
        self, user: User, fundraise: Fundraise, cents: int
    ) -> UsdFundraiseContribution:
        return UsdFundraiseContribution.objects.create(
            user=user, fundraise=fundraise, amount_cents=cents
        )

    def _add_update(self, doc: ResearchhubUnifiedDocument) -> RhCommentModel:
        thread = RhCommentThreadModel.objects.create(
            thread_type=AUTHOR_UPDATE, content_object=doc, created_by=self.author
        )
        return RhCommentModel.objects.create(
            thread=thread,
            created_by=self.author,
            comment_type=AUTHOR_UPDATE,
            comment_content_json={},
        )

    def _create_nonprofit(self, name: str = "Test Nonprofit") -> NonprofitOrg:
        return NonprofitOrg.objects.create(name=name, ein="12-3456789")

    def _link_nonprofit(
        self, nonprofit: NonprofitOrg, fundraise: Fundraise
    ) -> NonprofitFundraiseLink:
        return NonprofitFundraiseLink.objects.create(
            nonprofit=nonprofit, fundraise=fundraise
        )


class PortfolioOverviewTest(BaseDashboardTest):
    """Tests for portfolio overview metrics."""

    def test_empty_for_new_user(self) -> None:
        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["total_distributed_usd"], 0.0)
        self.assertEqual(result["active_rfps"], {"active": 0, "total": 0})
        self.assertEqual(result["total_applicants"], 0)
        self.assertEqual(result["matched_funding_usd"], 0.0)
        self.assertEqual(result["recent_updates"], 0)
        self.assertEqual(result["proposals_funded"], 0)

    def test_with_full_activity(self) -> None:
        # Arrange
        grant1 = self._create_grant(self.funder, Grant.OPEN)
        grant2 = self._create_grant(self.funder, Grant.OPEN)
        self._create_grant(self.funder, Grant.CLOSED)

        _, post1 = self._create_fundraise(self.other_user)
        _, post2 = self._create_fundraise(self.author)
        self._apply_to_grant(grant1, self.other_user, post1)
        self._apply_to_grant(grant2, self.author, post2)

        proposal, _ = self._create_fundraise(self.author)
        self._contribute_usd(self.funder, proposal, 10000)
        self._contribute_usd(self.other_user, proposal, 20000)
        self._add_update(proposal.unified_document)
        self._add_update(proposal.unified_document)

        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["active_rfps"], {"active": 2, "total": 3})
        self.assertEqual(result["total_applicants"], 2)
        self.assertEqual(result["total_distributed_usd"], 100.0)
        self.assertEqual(result["matched_funding_usd"], 200.0)
        self.assertEqual(result["recent_updates"], 2)
        self.assertEqual(result["proposals_funded"], 1)

    def test_excludes_refunded_contributions(self) -> None:
        # Arrange
        proposal, _ = self._create_fundraise(self.author)
        self._contribute_usd(self.funder, proposal, 10000)
        refunded = self._contribute_usd(self.funder, proposal, 5000)
        refunded.is_refunded = True
        refunded.save()

        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["total_distributed_usd"], 100.0)
        self.assertEqual(result["proposals_funded"], 1)

    def test_excludes_updates_older_than_30_days(self) -> None:
        # Arrange
        proposal, _ = self._create_fundraise(self.author)
        self._contribute_usd(self.funder, proposal, 10000)
        update = self._add_update(proposal.unified_document)
        RhCommentModel.objects.filter(id=update.id).update(
            created_date=timezone.now() - timezone.timedelta(days=31)
        )

        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["recent_updates"], 0)

    def test_deduplicates_applicants_across_grants(self) -> None:
        # Arrange
        grant1 = self._create_grant(self.funder)
        grant2 = self._create_grant(self.funder)
        _, post1 = self._create_fundraise(self.other_user)
        _, post2 = self._create_fundraise(self.other_user)
        self._apply_to_grant(grant1, self.other_user, post1)
        self._apply_to_grant(grant2, self.other_user, post2)

        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["total_applicants"], 1)

    def test_deduplicates_proposals_funded_with_both_payment_types(self) -> None:
        # Arrange
        proposal, _ = self._create_fundraise(self.author)
        self._contribute_rsc(self.funder, proposal, "100")
        self._contribute_usd(self.funder, proposal, 5000)

        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["proposals_funded"], 1)


class MilestonesTest(BaseDashboardTest):
    """Tests for milestone calculations."""

    def test_returns_first_tier_for_zero_values(self) -> None:
        # Act
        result = self.service.get_overview()

        # Assert
        milestones = result["impact"]["milestones"]
        self.assertEqual(milestones["funding_contributed"], {"current": 0.0, "target": 1000.0})
        self.assertEqual(milestones["researchers_supported"], {"current": 0.0, "target": 1.0})
        self.assertEqual(milestones["matched_funding"], {"current": 0.0, "target": 1000.0})

    def test_advances_to_next_tier_when_exceeded(self) -> None:
        # Arrange
        proposal, _ = self._create_fundraise(self.author)
        self._contribute_usd(self.funder, proposal, 150000)  # $1500 > $1000 tier

        # Act
        result = self.service.get_overview()

        # Assert
        milestones = result["impact"]["milestones"]
        self.assertEqual(milestones["funding_contributed"]["current"], 1500.0)
        self.assertEqual(milestones["funding_contributed"]["target"], 5000.0)


class FundingOverTimeTest(BaseDashboardTest):
    """Tests for funding over time chart data."""

    def test_returns_six_months_for_empty_user(self) -> None:
        # Act
        result = self.service.get_overview()

        # Assert
        funding_over_time = result["impact"]["funding_over_time"]
        self.assertEqual(len(funding_over_time), 6)
        for point in funding_over_time:
            self.assertEqual(point["user_contributions"], 0.0)
            self.assertEqual(point["matched_contributions"], 0.0)

    def test_aggregates_contributions_by_month(self) -> None:
        # Arrange
        proposal, _ = self._create_fundraise(self.author)
        self._contribute_usd(self.funder, proposal, 10000)
        self._contribute_usd(self.other_user, proposal, 5000)

        # Act
        result = self.service.get_overview()

        # Assert
        funding_over_time = result["impact"]["funding_over_time"]
        current_month = funding_over_time[-1]
        self.assertEqual(current_month["user_contributions"], 100.0)
        self.assertEqual(current_month["matched_contributions"], 50.0)


class TopicBreakdownTest(BaseDashboardTest):
    """Tests for topic breakdown chart data."""

    def test_returns_empty_for_no_contributions(self) -> None:
        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["impact"]["topic_breakdown"], [])

    def test_aggregates_by_hub(self) -> None:
        # Arrange
        proposal1, _ = self._create_fundraise(self.author, hubs=[self.hub])
        proposal2, _ = self._create_fundraise(self.author, hubs=[self.hub2])
        self._contribute_usd(self.funder, proposal1, 10000)
        self._contribute_usd(self.funder, proposal2, 5000)

        # Act
        result = self.service.get_overview()

        # Assert
        topics = result["impact"]["topic_breakdown"]
        self.assertEqual(len(topics), 2)
        self.assertEqual(topics[0]["name"], "Test Hub")
        self.assertEqual(topics[0]["amount_usd"], 100.0)
        self.assertEqual(topics[1]["name"], "Second Hub")
        self.assertEqual(topics[1]["amount_usd"], 50.0)

    def test_limits_to_top_six(self) -> None:
        # Arrange
        for i in range(8):
            hub = Hub.objects.create(name=f"Hub {i}")
            proposal, _ = self._create_fundraise(self.author, hubs=[hub])
            self._contribute_usd(self.funder, proposal, (i + 1) * 1000)

        # Act
        result = self.service.get_overview()

        # Assert
        topics = result["impact"]["topic_breakdown"]
        self.assertEqual(len(topics), 6)
        self.assertEqual(topics[0]["name"], "Hub 7")  # Highest amount


class UpdateFrequencyTest(BaseDashboardTest):
    """Tests for update frequency histogram data."""

    def test_returns_empty_buckets_for_no_contributions(self) -> None:
        # Act
        result = self.service.get_overview()

        # Assert
        buckets = result["impact"]["update_frequency"]
        self.assertEqual(len(buckets), 4)
        self.assertEqual(buckets[0], {"bucket": "0", "count": 0})

    def test_buckets_proposals_by_update_count(self) -> None:
        # Arrange
        proposal_0, _ = self._create_fundraise(self.author)
        proposal_1, _ = self._create_fundraise(self.author)
        proposal_3, _ = self._create_fundraise(self.author)
        proposal_5, _ = self._create_fundraise(self.author)

        self._contribute_usd(self.funder, proposal_0, 1000)
        self._contribute_usd(self.funder, proposal_1, 1000)
        self._contribute_usd(self.funder, proposal_3, 1000)
        self._contribute_usd(self.funder, proposal_5, 1000)

        self._add_update(proposal_1.unified_document)
        for _ in range(3):
            self._add_update(proposal_3.unified_document)
        for _ in range(5):
            self._add_update(proposal_5.unified_document)

        # Act
        result = self.service.get_overview()

        # Assert
        buckets = {b["bucket"]: b["count"] for b in result["impact"]["update_frequency"]}
        self.assertEqual(buckets["0"], 1)
        self.assertEqual(buckets["1"], 1)
        self.assertEqual(buckets["2-3"], 1)
        self.assertEqual(buckets["4+"], 1)

    def test_excludes_updates_older_than_180_days(self) -> None:
        # Arrange
        proposal, _ = self._create_fundraise(self.author)
        self._contribute_usd(self.funder, proposal, 1000)
        update = self._add_update(proposal.unified_document)
        RhCommentModel.objects.filter(id=update.id).update(
            created_date=timezone.now() - timezone.timedelta(days=181)
        )

        # Act
        result = self.service.get_overview()

        # Assert
        buckets = {b["bucket"]: b["count"] for b in result["impact"]["update_frequency"]}
        self.assertEqual(buckets["0"], 1)


class InstitutionsSupportedTest(BaseDashboardTest):
    """Tests for institutions supported data."""

    def test_returns_empty_for_no_contributions(self) -> None:
        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["impact"]["institutions_supported"], [])

    def test_aggregates_by_nonprofit(self) -> None:
        # Arrange
        nonprofit1 = self._create_nonprofit("Harvard")
        nonprofit2 = self._create_nonprofit("Stanford")

        proposal1, _ = self._create_fundraise(self.author)
        proposal2, _ = self._create_fundraise(self.author)

        self._link_nonprofit(nonprofit1, proposal1)
        self._link_nonprofit(nonprofit2, proposal2)

        self._contribute_usd(self.funder, proposal1, 10000)
        self._contribute_usd(self.funder, proposal2, 5000)

        # Act
        result = self.service.get_overview()

        # Assert
        institutions = result["impact"]["institutions_supported"]
        self.assertEqual(len(institutions), 2)
        self.assertEqual(institutions[0]["name"], "Harvard")
        self.assertEqual(institutions[0]["amount_usd"], 100.0)
        self.assertEqual(institutions[0]["project_count"], 1)

    def test_combines_multiple_projects_per_institution(self) -> None:
        # Arrange
        nonprofit = self._create_nonprofit("MIT")

        proposal1, _ = self._create_fundraise(self.author)
        proposal2, _ = self._create_fundraise(self.author)

        self._link_nonprofit(nonprofit, proposal1)
        self._link_nonprofit(nonprofit, proposal2)

        self._contribute_usd(self.funder, proposal1, 10000)
        self._contribute_usd(self.funder, proposal2, 5000)

        # Act
        result = self.service.get_overview()

        # Assert
        institutions = result["impact"]["institutions_supported"]
        self.assertEqual(len(institutions), 1)
        self.assertEqual(institutions[0]["amount_usd"], 150.0)
        self.assertEqual(institutions[0]["project_count"], 2)
