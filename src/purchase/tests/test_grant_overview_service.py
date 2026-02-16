from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from purchase.models import Fundraise, Grant, GrantApplication, Purchase
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.usd_fundraise_contribution_model import UsdFundraiseContribution
from purchase.services.funding_overview_service import GrantOverviewService
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT as GRANT_DOC_TYPE, PREREGISTRATION
from user.tests.helpers import create_random_authenticated_user


class TestGrantOverviewService(TestCase):
    def setUp(self):
        self.service = GrantOverviewService()
        self.grant_creator = create_random_authenticated_user("grant_creator")
        self.researcher = create_random_authenticated_user("researcher")
        RscExchangeRate.objects.create(rate=0.5, real_rate=0.5, price_source="COIN_GECKO", target_currency="USD")
        self.fundraise_ct = ContentType.objects.get_for_model(Fundraise)

    def _create_grant(self, amount=10000, end_date=None):
        """Create a grant owned by the grant creator."""
        post = create_post(created_by=self.grant_creator, document_type=GRANT_DOC_TYPE)
        return Grant.objects.create(
            created_by=self.grant_creator,
            unified_document=post.unified_document,
            amount=Decimal(str(amount)),
            status=Grant.OPEN,
            end_date=end_date,
        )

    def _create_proposal_for_grant(self, grant, created_by=None):
        """Create a proposal (fundraise) that applied to the given grant."""
        creator = created_by or self.researcher
        post = create_post(created_by=creator, document_type=PREREGISTRATION)
        fundraise = Fundraise.objects.create(
            created_by=creator,
            unified_document=post.unified_document,
            goal_amount=Decimal("1000"),
            goal_currency="USD",
        )
        GrantApplication.objects.create(grant=grant, preregistration_post=post, applicant=creator)
        return fundraise

    def _contribute(self, user, fundraise, rsc=0, usd_cents=0):
        """Create contribution from user to fundraise."""
        if rsc:
            Purchase.objects.create(
                user=user,
                content_type=self.fundraise_ct,
                object_id=fundraise.id,
                purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                purchase_method=Purchase.OFF_CHAIN,
                amount=str(rsc),
            )
        if usd_cents:
            UsdFundraiseContribution.objects.create(
                user=user,
                fundraise=fundraise,
                amount_cents=usd_cents,
                fee_cents=0,
                origin_fund_id="test-fund",
                destination_org_id="test-org",
            )

    def test_returns_expected_structure(self):
        grant = self._create_grant(amount=750000)

        result = self.service.get_grant_overview(self.grant_creator, grant)

        expected_keys = {
            "budget_used_usd", "budget_total_usd", "matched_funding_usd",
            "total_proposals", "proposals_funded", "deadline",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_empty_grant_returns_zeros(self):
        grant = self._create_grant()

        result = self.service.get_grant_overview(self.grant_creator, grant)

        self.assertEqual(result["budget_used_usd"], 0.0)
        self.assertEqual(result["budget_total_usd"], 10000.0)
        self.assertEqual(result["matched_funding_usd"], 0.0)
        self.assertEqual(result["total_proposals"], 0)
        self.assertEqual(result["proposals_funded"], 0)

    def test_budget_used_calculates_user_contributions(self):
        grant = self._create_grant(amount=10000)
        fundraise = self._create_proposal_for_grant(grant)
        self._contribute(self.grant_creator, fundraise, rsc=200, usd_cents=5000)  # $100 + $50 = $150

        result = self.service.get_grant_overview(self.grant_creator, grant)

        self.assertEqual(result["budget_used_usd"], 150.0)
        self.assertEqual(result["budget_total_usd"], 10000.0)

    def test_matched_funding_excludes_user_contributions(self):
        grant = self._create_grant()
        fundraise = self._create_proposal_for_grant(grant)
        other_user = create_random_authenticated_user("other")
        self._contribute(self.grant_creator, fundraise, rsc=100)  # $50 - not matched
        self._contribute(other_user, fundraise, rsc=200)  # $100 - matched

        result = self.service.get_grant_overview(self.grant_creator, grant)

        self.assertEqual(result["matched_funding_usd"], 100.0)

    def test_proposals_funded_counts_correctly(self):
        grant = self._create_grant()
        r1 = create_random_authenticated_user("r1")
        r2 = create_random_authenticated_user("r2")
        r3 = create_random_authenticated_user("r3")
        f1 = self._create_proposal_for_grant(grant, r1)
        f2 = self._create_proposal_for_grant(grant, r2)
        self._create_proposal_for_grant(grant, r3)  # Not funded
        self._contribute(self.grant_creator, f1, rsc=100)
        self._contribute(self.grant_creator, f2, rsc=100)

        result = self.service.get_grant_overview(self.grant_creator, grant)

        self.assertEqual(result["proposals_funded"], 2)

    def test_total_proposals_counts_all_applications(self):
        grant = self._create_grant()
        r1 = create_random_authenticated_user("r1")
        r2 = create_random_authenticated_user("r2")
        r3 = create_random_authenticated_user("r3")
        self._create_proposal_for_grant(grant, r1)
        self._create_proposal_for_grant(grant, r2)
        self._create_proposal_for_grant(grant, r3)

        result = self.service.get_grant_overview(self.grant_creator, grant)

        self.assertEqual(result["total_proposals"], 3)

    def test_deadline_returns_none_when_unset(self):
        grant = self._create_grant()

        result = self.service.get_grant_overview(self.grant_creator, grant)

        self.assertIsNone(result["deadline"])

    def test_deadline_returns_datetime_when_set(self):
        end_date = timezone.now() + timedelta(days=30)
        grant = self._create_grant(end_date=end_date)

        result = self.service.get_grant_overview(self.grant_creator, grant)

        self.assertEqual(result["deadline"], end_date)
