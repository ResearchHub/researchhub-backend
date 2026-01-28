import uuid
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from funding_dashboard.services import DashboardService
from hub.models import Hub
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
        self, creator: User, status: str = Fundraise.OPEN
    ) -> tuple[Fundraise, ResearchhubPost]:
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PREREGISTRATION)
        doc.hubs.add(self.hub)
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

    def test_overview_empty_for_new_user(self):
        # Arrange - handled by setUp

        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["total_distributed_usd"], 0.0)
        self.assertEqual(result["active_rfps"], {"active": 0, "total": 0})
        self.assertEqual(result["total_applicants"], 0)
        self.assertEqual(result["matched_funding_usd"], 0.0)
        self.assertEqual(result["recent_updates"], 0)
        self.assertEqual(result["proposals_funded"], 0)

    def test_overview_with_full_activity(self):
        # Arrange
        # Funder creates grants (RFPs)
        grant1 = self._create_grant(self.funder, Grant.OPEN)
        grant2 = self._create_grant(self.funder, Grant.OPEN)
        self._create_grant(self.funder, Grant.CLOSED)

        # Others apply to funder's grants
        proposal1, post1 = self._create_fundraise(self.other_user)
        proposal2, post2 = self._create_fundraise(self.author)
        self._apply_to_grant(grant1, self.other_user, post1)
        self._apply_to_grant(grant2, self.author, post2)

        # Funder contributes to author's proposal
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

    def test_excludes_refunded_contributions(self):
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

    def test_excludes_updates_older_than_30_days(self):
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

    def test_deduplicates_applicants_across_grants(self):
        # Arrange
        grant1 = self._create_grant(self.funder)
        grant2 = self._create_grant(self.funder)
        _, post1 = self._create_fundraise(self.other_user)
        self._apply_to_grant(grant1, self.other_user, post1)
        # Same user applies to second grant with different proposal
        _, post2 = self._create_fundraise(self.other_user)
        self._apply_to_grant(grant2, self.other_user, post2)

        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["total_applicants"], 1)

    def test_deduplicates_proposals_funded_with_both_payment_types(self):
        # Arrange
        proposal, _ = self._create_fundraise(self.author)
        self._contribute_rsc(self.funder, proposal, "100")
        self._contribute_usd(self.funder, proposal, 5000)

        # Act
        result = self.service.get_overview()

        # Assert
        self.assertEqual(result["proposals_funded"], 1)
