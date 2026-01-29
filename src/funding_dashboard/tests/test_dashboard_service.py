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


class DashboardServiceTest(TestCase):

    def setUp(self) -> None:
        self.funder = User.objects.create_user(username="funder", email="f@t.com", password=uuid.uuid4().hex)
        self.other = User.objects.create_user(username="other", email="o@t.com", password=uuid.uuid4().hex)
        self.author = User.objects.create_user(username="author", email="a@t.com", password=uuid.uuid4().hex)
        self.hub = Hub.objects.create(name="Hub A")
        self.hub2 = Hub.objects.create(name="Hub B")
        self.service = DashboardService(self.funder)
        self.ct = ContentType.objects.get_for_model(Fundraise)
        RscExchangeRate.objects.create(rate=1.0, real_rate=1.0)

    def _grant(self, status=Grant.OPEN) -> Grant:
        doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        doc.hubs.add(self.hub)
        ResearchhubPost.objects.create(created_by=self.funder, document_type=GRANT, unified_document=doc)
        return Grant.objects.create(created_by=self.funder, unified_document=doc, amount=Decimal("10000"), description="g", status=status)

    def _fundraise(self, creator=None, hubs=None) -> Fundraise:
        creator = creator or self.author
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PREREGISTRATION)
        for h in hubs or [self.hub]:
            doc.hubs.add(h)
        post = ResearchhubPost.objects.create(created_by=creator, document_type=PREREGISTRATION, unified_document=doc)
        return Fundraise.objects.create(created_by=creator, unified_document=doc, goal_amount=10000), post

    def _usd(self, user, fundraise, cents) -> UsdFundraiseContribution:
        return UsdFundraiseContribution.objects.create(user=user, fundraise=fundraise, amount_cents=cents)

    def _rsc(self, user, fundraise, amount) -> Purchase:
        return Purchase.objects.create(
            user=user, content_type=self.ct, object_id=fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION, purchase_method=Purchase.OFF_CHAIN,
            paid_status=Purchase.PAID, amount=amount
        )

    def _update(self, doc) -> RhCommentModel:
        thread = RhCommentThreadModel.objects.create(thread_type=AUTHOR_UPDATE, content_object=doc, created_by=self.author)
        return RhCommentModel.objects.create(thread=thread, created_by=self.author, comment_type=AUTHOR_UPDATE, comment_content_json={})

    def test_empty_state_returns_zeros_and_empty_arrays(self) -> None:
        # Arrange - setUp provides fresh user with no activity

        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["total_distributed_usd"], 0.0)
        self.assertEqual(result["active_rfps"], {"active": 0, "total": 0})
        self.assertEqual(result["total_applicants"], 0)
        self.assertEqual(result["matched_funding_usd"], 0.0)
        self.assertEqual(result["recent_updates"], 0)
        self.assertEqual(result["proposals_funded"], 0)
        self.assertEqual(result["impact"]["milestones"]["funding_contributed"], {"current": 0.0, "target": 1000.0})
        self.assertEqual(len(result["impact"]["funding_over_time"]), 6)
        self.assertEqual(result["impact"]["topic_breakdown"], [])
        self.assertEqual(len(result["impact"]["update_frequency"]), 4)
        self.assertEqual(result["impact"]["institutions_supported"], [])

    def test_full_activity_calculates_all_metrics(self) -> None:
        # Arrange
        g1, g2 = self._grant(Grant.OPEN), self._grant(Grant.OPEN)
        self._grant(Grant.CLOSED)
        f1, p1 = self._fundraise(self.other)
        f2, p2 = self._fundraise(self.author)
        GrantApplication.objects.create(grant=g1, applicant=self.other, preregistration_post=p1)
        GrantApplication.objects.create(grant=g2, applicant=self.author, preregistration_post=p2)
        proposal, _ = self._fundraise(hubs=[self.hub, self.hub2])
        nonprofit = NonprofitOrg.objects.create(name="MIT", ein="12-345")
        NonprofitFundraiseLink.objects.create(nonprofit=nonprofit, fundraise=proposal)
        self._usd(self.funder, proposal, 10000)
        self._usd(self.other, proposal, 20000)
        self._update(proposal.unified_document)
        self._update(proposal.unified_document)

        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["active_rfps"], {"active": 2, "total": 3})
        self.assertEqual(result["total_applicants"], 2)
        self.assertEqual(result["total_distributed_usd"], 100.0)
        self.assertEqual(result["matched_funding_usd"], 200.0)
        self.assertEqual(result["recent_updates"], 2)
        self.assertEqual(result["proposals_funded"], 1)
        self.assertEqual(result["impact"]["milestones"]["funding_contributed"]["target"], 1000.0)
        self.assertEqual(result["impact"]["funding_over_time"][-1]["user_contributions"], 100.0)
        self.assertEqual(len(result["impact"]["topic_breakdown"]), 2)
        self.assertEqual(result["impact"]["institutions_supported"][0]["name"], "MIT")

    def test_excludes_refunded_contributions_and_old_updates(self) -> None:
        # Arrange
        proposal, _ = self._fundraise()
        self._usd(self.funder, proposal, 10000)
        refunded = self._usd(self.funder, proposal, 5000)
        refunded.is_refunded = True
        refunded.save()
        old_update = self._update(proposal.unified_document)
        RhCommentModel.objects.filter(id=old_update.id).update(
            created_date=timezone.now() - timezone.timedelta(days=31)
        )

        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["total_distributed_usd"], 100.0)
        self.assertEqual(result["recent_updates"], 0)

    def test_deduplicates_applicants_and_proposals(self) -> None:
        # Arrange
        g1, g2 = self._grant(), self._grant()
        f1, p1 = self._fundraise(self.other)
        f2, p2 = self._fundraise(self.other)
        GrantApplication.objects.create(grant=g1, applicant=self.other, preregistration_post=p1)
        GrantApplication.objects.create(grant=g2, applicant=self.other, preregistration_post=p2)
        proposal, _ = self._fundraise()
        self._rsc(self.funder, proposal, "100")
        self._usd(self.funder, proposal, 5000)

        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["total_applicants"], 1)
        self.assertEqual(result["proposals_funded"], 1)

    def test_milestone_advances_to_next_tier(self) -> None:
        # Arrange
        proposal, _ = self._fundraise()
        self._usd(self.funder, proposal, 150000)

        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["impact"]["milestones"]["funding_contributed"]["current"], 1500.0)
        self.assertEqual(result["impact"]["milestones"]["funding_contributed"]["target"], 5000.0)

    def test_update_frequency_buckets_and_180_day_cutoff(self) -> None:
        # Arrange
        proposals = [self._fundraise()[0] for _ in range(4)]
        for p in proposals:
            self._usd(self.funder, p, 1000)
        self._update(proposals[1].unified_document)
        for _ in range(3):
            self._update(proposals[2].unified_document)
        for _ in range(5):
            self._update(proposals[3].unified_document)
        old = self._update(proposals[0].unified_document)
        RhCommentModel.objects.filter(id=old.id).update(
            created_date=timezone.now() - timezone.timedelta(days=181)
        )

        # Act
        result = self.service.get_overview()

        # Assert
        buckets = {b["bucket"]: b["count"] for b in result["impact"]["update_frequency"]}
        self.assertEqual(buckets, {"0": 1, "1": 1, "2-3": 1, "4+": 1})

    def test_topic_breakdown_limits_to_six_sorted_by_amount(self) -> None:
        # Arrange
        for i in range(8):
            hub = Hub.objects.create(name=f"Hub {i}")
            proposal, _ = self._fundraise(hubs=[hub])
            self._usd(self.funder, proposal, (i + 1) * 1000)

        # Act
        result = self.service.get_overview()

        # Assert
        topics = result["impact"]["topic_breakdown"]
        self.assertEqual(len(topics), 6)
        self.assertEqual(topics[0]["name"], "Hub 7")
        self.assertEqual(topics[0]["amount_usd"], 80.0)
