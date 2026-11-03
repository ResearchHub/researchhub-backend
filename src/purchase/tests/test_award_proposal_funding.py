from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from rest_framework.test import APITestCase

from purchase.models import (
    Balance,
    FundingPool,
    Fundraise,
    Grant,
    GrantApplication,
    RscExchangeRate,
    UsdFundraiseContribution,
)
from purchase.related_models.constants.currency import RSC, USD
from purchase.services.funding_pool_service import FundingPoolService
from purchase.services.fundraise_service import (
    AWARD_PROPOSAL_CONTRIBUTION_DENIED,
    FundraiseService,
)
from purchase.tasks import complete_eligible_fundraises
from reputation.models import BountyFee
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT as GRANT_DOC,
)
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
)
from user.tests.helpers import create_random_authenticated_user, create_user


class AwardProposalFundingTests(APITestCase):
    """Award proposal payments stay in escrow until the daily job pays the author."""

    def setUp(self):
        cache.clear()
        self.grant_creator = create_random_authenticated_user("award_grant_creator")
        self.community_user = create_random_authenticated_user("award_community")
        self.moderator = create_random_authenticated_user(
            "award_moderator", moderator=True
        )
        self.fundraise_service = FundraiseService()
        self.pool_service = FundingPoolService()

        grant_post = create_post(created_by=self.grant_creator, document_type=GRANT_DOC)
        self.grant = Grant.objects.create(
            created_by=self.grant_creator,
            unified_document=grant_post.unified_document,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="Award Org",
            description="Award RFP",
            status=Grant.OPEN,
            funding_mechanism=Grant.AWARD,
        )
        self.pool = self.pool_service.create_pool_for_grant(self.grant)
        self.applicant, self.application, self.fundraise = self._create_proposal()

        BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)
        RscExchangeRate.objects.create(
            rate=0.5,
            real_rate=0.5,
            price_source="COIN_GECKO",
            target_currency="USD",
        )
        self.exchange_rate_patcher = patch(
            "purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.get_latest",
            return_value=0.5,
        )
        self.exchange_rate_patcher.start()
        self.addCleanup(self.exchange_rate_patcher.stop)
        create_user(email="bank@researchhub.com")
        create_user(email="revenue@researchhub.com")

    def test_community_contributions_rejected_and_creator_can_pay(self):
        """RSC and USD from anyone but the grant creator are rejected.

        The creator's RSC stays in escrow and leaves the fundraise open.
        Skipping the self-contribution check, which the payment webhook does,
        does not open the proposal to the community.
        """
        # Arrange
        self._give_available_balance(self.community_user, Decimal(1000))
        self._give_available_balance(self.grant_creator, Decimal(1000))
        balance_before = self.community_user.get_available_balance()

        # Act
        for user in (self.community_user, self.moderator, self.applicant):
            purchase, error = self.fundraise_service.create_contribution(
                user=user,
                fundraise=self.fundraise,
                amount=Decimal(10),
                currency=RSC,
                use_credits=False,
            )
            usd_contribution, usd_error = self.fundraise_service.create_contribution(
                user=user,
                fundraise=self.fundraise,
                amount=10000,
                currency=USD,
                origin_fund_id="fund_community",
            )
            # Assert
            self.assertIsNone(purchase)
            self.assertEqual(error, AWARD_PROPOSAL_CONTRIBUTION_DENIED)
            self.assertIsNone(usd_contribution)
            self.assertEqual(usd_error, AWARD_PROPOSAL_CONTRIBUTION_DENIED)

        webhook_purchase, webhook_error = self.fundraise_service.create_contribution(
            user=self.community_user,
            fundraise=self.fundraise,
            amount=Decimal(10),
            currency=RSC,
            check_self_contribution=False,
            use_credits=False,
        )
        creator_usd, creator_usd_error = self.fundraise_service.create_contribution(
            user=self.grant_creator,
            fundraise=self.fundraise,
            amount=10000,
            currency=USD,
            origin_fund_id="fund_creator",
        )
        creator_purchase, creator_error = self.fundraise_service.create_contribution(
            user=self.grant_creator,
            fundraise=self.fundraise,
            amount=Decimal(20),
            currency=RSC,
            use_credits=False,
        )

        # Assert
        self.assertIsNone(webhook_purchase)
        self.assertEqual(webhook_error, AWARD_PROPOSAL_CONTRIBUTION_DENIED)
        self.assertEqual(self.community_user.get_available_balance(), balance_before)
        self.assertEqual(UsdFundraiseContribution.objects.count(), 0)
        self.assertIsNone(creator_usd)
        self.assertEqual(creator_usd_error, "Fundraise nonprofit org is not set")
        self.assertIsNone(creator_error)
        self._refresh_fundraise(self.fundraise)
        self.assertEqual(self.fundraise.status, Fundraise.OPEN)
        self.assertEqual(self.fundraise.escrow.amount_holding, Decimal(20))
        self.assertEqual(self.fundraise.get_amount_raised(currency=RSC), 20.0)
        self.assertEqual(creator_purchase.object_id, self.fundraise.id)

    def test_funding_grant_still_accepts_community_contributions(self):
        """A funding-mechanism proposal is not limited to the grant creator."""
        # Arrange
        funding_post = create_post(
            created_by=self.grant_creator, document_type=GRANT_DOC
        )
        funding_grant = Grant.objects.create(
            created_by=self.grant_creator,
            unified_document=funding_post.unified_document,
            amount=Decimal("1000.00"),
            currency="USD",
            organization="Funding Org",
            description="Funding RFP",
            status=Grant.OPEN,
            funding_mechanism=Grant.FUNDING,
        )
        _applicant, _application, fundraise = self._create_proposal(grant=funding_grant)
        self._give_available_balance(self.community_user, Decimal(1000))

        # Act
        purchase, error = self.fundraise_service.create_contribution(
            user=self.community_user,
            fundraise=fundraise,
            amount=Decimal(15),
            currency=RSC,
            use_credits=False,
        )

        # Assert
        self.assertIsNone(error)
        self._refresh_fundraise(fundraise)
        self.assertEqual(fundraise.status, Fundraise.OPEN)
        self.assertEqual(fundraise.escrow.amount_holding, Decimal(15))
        self.assertEqual(purchase.amount, Decimal(15))

    def test_award_pool_still_accepts_community_contributions(self):
        """Community crowdfunding stays on the RFP pool."""
        # Arrange
        self._give_available_balance(self.community_user, Decimal(1000))

        # Act
        purchase = self.pool_service.create_contribution(
            user=self.community_user,
            pool=self.pool,
            amount=Decimal(25),
            use_credits=False,
        )

        # Assert
        self.pool.refresh_from_db()
        self.assertEqual(purchase.object_id, self.pool.id)
        self.assertEqual(self.pool.amount_holding, Decimal(25))
        self.assertEqual(self.fundraise.status, Fundraise.OPEN)
        self.assertEqual(self.fundraise.escrow.amount_holding, Decimal(0))

    def test_allocation_and_creator_payment_stay_open(self):
        """Pool RSC and the creator's payment both sit in escrow and count as raised."""
        # Arrange
        self._seed_pool(Decimal(100))
        self._give_available_balance(self.grant_creator, Decimal(1000))

        # Act
        self.pool_service.distribute(
            self.pool, self.grant_creator, Decimal(30), self.application.id
        )
        _purchase, error = self.fundraise_service.create_contribution(
            user=self.grant_creator,
            fundraise=self.fundraise,
            amount=Decimal(20),
            currency=RSC,
            use_credits=False,
        )

        # Assert
        self.assertIsNone(error)
        self._refresh_fundraise(self.fundraise)
        self.pool.refresh_from_db()
        self.assertEqual(self.fundraise.status, Fundraise.OPEN)
        self.assertEqual(self.fundraise.escrow.amount_holding, Decimal(50))
        self.assertEqual(self.fundraise.escrow.amount_paid, Decimal(0))
        self.assertEqual(self.fundraise.get_amount_raised(currency=RSC), 50.0)
        self.assertEqual(self.pool.amount_holding, Decimal(70))
        self.assertEqual(self.pool.amount_distributed, Decimal(30))

    def test_daily_job_pays_author_and_rejects_later_allocation(self):
        """The daily job pays an award escrow once the proposal is a week old.

        An empty award escrow stays open. A normal fundraise that met its goal
        still completes in the same run. After payout, that proposal cannot
        take more pool RSC, and a proposal that is still open can.
        """
        # Arrange
        self._seed_pool(Decimal(100))
        self._give_available_balance(self.grant_creator, Decimal(1000))
        self.pool_service.distribute(
            self.pool, self.grant_creator, Decimal(30), self.application.id
        )
        _purchase, error = self.fundraise_service.create_contribution(
            user=self.grant_creator,
            fundraise=self.fundraise,
            amount=Decimal(20),
            currency=RSC,
            use_credits=False,
        )
        self.assertIsNone(error)
        empty_applicant, _empty_application, empty_fundraise = self._create_proposal()
        self._age(empty_fundraise, days=8)
        _other_applicant, other_application, other_fundraise = self._create_proposal()
        normal_author = create_random_authenticated_user("normal_fundraise_author")
        normal_post = create_post(
            created_by=normal_author, document_type=PREREGISTRATION
        )
        normal_fundraise = self.fundraise_service.create_fundraise_with_escrow(
            user=normal_author,
            unified_document=normal_post.unified_document,
            goal_amount=Decimal("100.00"),
            goal_currency=USD,
            status=Fundraise.OPEN,
        )
        self._age(normal_fundraise, days=8)
        normal_fundraise.escrow.amount_holding = Decimal("200.00")
        normal_fundraise.escrow.save(update_fields=["amount_holding"])
        author_balance_before = self.applicant.get_available_balance()

        # Act — too new to pay, but an aged normal fundraise still completes
        early_result = complete_eligible_fundraises()

        # Assert
        self._refresh_fundraise(self.fundraise)
        self._refresh_fundraise(empty_fundraise)
        self._refresh_fundraise(normal_fundraise)
        self.assertEqual(early_result["completed_count"], 1)
        self.assertEqual(early_result["error_count"], 0)
        self.assertEqual(self.fundraise.status, Fundraise.OPEN)
        self.assertEqual(self.fundraise.escrow.amount_holding, Decimal(50))
        self.assertEqual(empty_fundraise.status, Fundraise.OPEN)
        self.assertEqual(normal_fundraise.status, Fundraise.COMPLETED)

        # Act — pay the award escrow on the next run after it is a week old
        self._age(self.fundraise, days=8)
        payout_result = complete_eligible_fundraises()

        # Assert
        self._refresh_fundraise(self.fundraise)
        self._refresh_fundraise(empty_fundraise)
        self.assertEqual(payout_result["completed_count"], 1)
        self.assertEqual(payout_result["error_count"], 0)
        self.assertEqual(self.fundraise.status, Fundraise.COMPLETED)
        self.assertEqual(self.fundraise.escrow.amount_holding, Decimal(0))
        self.assertEqual(self.fundraise.escrow.amount_paid, Decimal(50))
        self.assertEqual(self.fundraise.get_amount_raised(currency=RSC), 50.0)
        self.assertEqual(
            self.applicant.get_available_balance(),
            author_balance_before + Decimal(50),
        )
        self.assertEqual(empty_fundraise.status, Fundraise.OPEN)
        self.assertEqual(empty_applicant.id, empty_fundraise.created_by_id)

        # Later allocation is rejected. Another open proposal can still receive RSC.
        with self.assertRaises(ValueError) as rejected:
            self.pool_service.distribute(
                self.pool, self.grant_creator, Decimal(10), self.application.id
            )
        self.pool_service.distribute(
            self.pool, self.moderator, Decimal(10), other_application.id
        )

        # Assert
        self._refresh_fundraise(self.fundraise)
        self._refresh_fundraise(other_fundraise)
        self.pool.refresh_from_db()
        self.assertEqual(str(rejected.exception), "Fundraise is not open")
        self.assertEqual(self.fundraise.status, Fundraise.COMPLETED)
        self.assertEqual(self.fundraise.escrow.amount_paid, Decimal(50))
        self.assertEqual(other_fundraise.status, Fundraise.OPEN)
        self.assertEqual(other_fundraise.escrow.amount_holding, Decimal(10))
        self.assertEqual(self.pool.amount_holding, Decimal(60))
        self.assertEqual(self.pool.amount_distributed, Decimal(40))

    def test_completing_grant_leaves_proposal_escrow_untouched(self):
        """Completing the RFP does not pay or close proposal fundraises."""
        # Arrange
        self._seed_pool(Decimal(100))
        self.pool_service.distribute(
            self.pool, self.grant_creator, Decimal(40), self.application.id
        )
        self._refresh_fundraise(self.fundraise)
        self.pool.refresh_from_db()
        holding_before = self.fundraise.escrow.amount_holding
        paid_before = self.fundraise.escrow.amount_paid
        pool_holding_before = self.pool.amount_holding

        # Act
        self.client.force_authenticate(self.community_user)
        denied = self.client.post(f"/api/grant/{self.grant.id}/complete/")
        self.client.force_authenticate(self.moderator)
        completed = self.client.post(f"/api/grant/{self.grant.id}/complete/")

        # Assert
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.data["status"], Grant.COMPLETED)
        self.grant.refresh_from_db()
        self._refresh_fundraise(self.fundraise)
        self.pool.refresh_from_db()
        self.assertEqual(self.grant.status, Grant.COMPLETED)
        self.assertEqual(self.fundraise.status, Fundraise.OPEN)
        self.assertEqual(self.fundraise.escrow.amount_holding, holding_before)
        self.assertEqual(self.fundraise.escrow.amount_paid, paid_before)
        self.assertEqual(self.pool.amount_holding, pool_holding_before)
        self.assertEqual(self.pool.status, FundingPool.OPEN)

    def _create_proposal(self, grant=None):
        grant = grant or self.grant
        applicant = create_random_authenticated_user("award_applicant")
        proposal = create_post(created_by=applicant, document_type=PREREGISTRATION)
        application = GrantApplication.objects.create(
            grant=grant,
            preregistration_post=proposal,
            applicant=applicant,
        )
        fundraise = self.fundraise_service.create_fundraise_with_escrow(
            user=applicant,
            unified_document=proposal.unified_document,
            goal_amount=Decimal(0),
            goal_currency=USD,
            status=Fundraise.OPEN,
        )
        return applicant, application, fundraise

    def _give_available_balance(self, user, amount):
        distribution_ct = ContentType.objects.get(model="distribution")
        Balance.objects.create(amount=amount, user=user, content_type=distribution_ct)

    def _seed_pool(self, amount):
        contributor = create_random_authenticated_user("award_pool_backer")
        self._give_available_balance(contributor, Decimal(10000))
        self.pool_service.create_contribution(
            user=contributor,
            pool=self.pool,
            amount=amount,
            use_credits=False,
        )
        self.pool.refresh_from_db()

    def _age(self, fundraise, days):
        fundraise.start_date = datetime.now(UTC) - timedelta(days=days)
        fundraise.save(update_fields=["start_date"])

    def _refresh_fundraise(self, fundraise):
        fundraise.refresh_from_db()
        fundraise.escrow.refresh_from_db()
