from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from institution.models import Institution
from purchase.models import Fundraise, Grant, GrantApplication, Purchase
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from purchase.services.funding_overview_service import FundingOverviewService
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT as GRANT_DOC_TYPE,
)
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.related_models.author_institution import AuthorInstitution
from user.tests.helpers import create_random_authenticated_user


class TestFundingOverviewService(TestCase):
    def setUp(self):
        self.service = FundingOverviewService()
        self.user = create_random_authenticated_user("funder", moderator=True)
        self.fundraise_ct = ContentType.objects.get_for_model(Fundraise)
        RscExchangeRate.objects.create(
            rate=0.5, real_rate=0.5, price_source="COIN_GECKO", target_currency="USD"
        )

    def _create_grant_with_proposal(self, funder=None, applicant=None):
        """Create a grant, proposal post, fundraise, and application."""
        funder = funder or self.user
        applicant = applicant or create_random_authenticated_user("applicant")

        grant_post = create_post(created_by=funder, document_type=GRANT_DOC_TYPE)
        grant = Grant.objects.create(
            created_by=funder,
            unified_document=grant_post.unified_document,
            amount=Decimal("1000"),
            status=Grant.OPEN,
        )

        proposal_post = create_post(created_by=applicant, document_type=PREREGISTRATION)
        fundraise = Fundraise.objects.create(
            created_by=applicant,
            unified_document=proposal_post.unified_document,
            goal_amount=Decimal("1000"),
            goal_currency="USD",
        )

        GrantApplication.objects.create(
            grant=grant,
            preregistration_post=proposal_post,
            applicant=applicant,
        )

        return grant, proposal_post, fundraise, applicant

    def _contribute(self, user, fundraise, rsc=0, usd_cents=0):
        """Create RSC and/or USD contribution from user to fundraise."""
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

    def test_returns_expected_structure_with_zeros_for_new_user(self):
        # Arrange - uses setUp

        # Act
        result = self.service.get_funding_overview(self.user)

        # Assert
        self.assertEqual(result["matched_funds"], {"rsc": 0.0, "usd": 0.0})
        self.assertEqual(result["distributed_funds"], {"rsc": 0.0, "usd": 0.0})
        self.assertEqual(result["supported_proposals"], [])
        self.assertEqual(result["supported_institutions"], [])

    def test_distributed_funds_tracks_funder_contributions(self):
        # Arrange
        _, _, fundraise, _ = self._create_grant_with_proposal()
        self._contribute(self.user, fundraise, rsc=100, usd_cents=5000)

        # Act
        result = self.service.get_funding_overview(self.user)

        # Assert
        self.assertEqual(result["distributed_funds"]["rsc"], 100.0)
        self.assertEqual(result["distributed_funds"]["usd"], 50.0)

    def test_matched_funds_tracks_others_contributions(self):
        # Arrange
        _, _, fundraise, _ = self._create_grant_with_proposal()
        other_user = create_random_authenticated_user("other")
        self._contribute(other_user, fundraise, rsc=200, usd_cents=10000)

        # Act
        result = self.service.get_funding_overview(self.user)

        # Assert
        self.assertEqual(result["matched_funds"]["rsc"], 200.0)
        self.assertEqual(result["matched_funds"]["usd"], 100.0)

    def test_matched_funds_excludes_funder_contributions(self):
        # Arrange
        _, _, fundraise, _ = self._create_grant_with_proposal()
        self._contribute(self.user, fundraise, rsc=100)

        # Act
        result = self.service.get_funding_overview(self.user)

        # Assert
        self.assertEqual(result["matched_funds"]["rsc"], 0.0)
        self.assertEqual(result["matched_funds"]["usd"], 0.0)

    def test_supported_proposals_returns_funded_proposals(self):
        # Arrange
        _, proposal_post, fundraise, applicant = self._create_grant_with_proposal()
        self._contribute(self.user, fundraise, rsc=100)

        # Act
        result = self.service.get_funding_overview(self.user)

        # Assert
        self.assertEqual(len(result["supported_proposals"]), 1)
        proposal = result["supported_proposals"][0]
        self.assertEqual(proposal["id"], proposal_post.id)
        self.assertEqual(
            proposal["unified_document"]["id"], proposal_post.unified_document_id
        )
        self.assertEqual(proposal["unified_document"]["title"], proposal_post.title)
        self.assertEqual(proposal["unified_document"]["slug"], proposal_post.slug)
        self.assertEqual(proposal["created_by"]["id"], applicant.id)
        author = applicant.author_profile
        self.assertEqual(proposal["created_by"]["author_profile"]["id"], author.id)
        self.assertEqual(
            proposal["created_by"]["author_profile"]["first_name"], author.first_name
        )
        self.assertEqual(
            proposal["created_by"]["author_profile"]["last_name"], author.last_name
        )
        self.assertEqual(result["supported_institutions"], [])

    def test_supported_proposals_empty_when_not_funded(self):
        # Arrange
        self._create_grant_with_proposal()

        # Act
        result = self.service.get_funding_overview(self.user)

        # Assert
        self.assertEqual(result["supported_proposals"], [])
        self.assertEqual(result["supported_institutions"], [])

    def test_supported_institutions_one_linked_institution(self):
        _, proposal_post, fundraise, applicant = self._create_grant_with_proposal()
        institution = Institution.objects.create(
            openalex_id="https://openalex.org/S1234567890",
            ror_id="https://ror.org/00test0001",
            display_name="Test University",
            type="education",
            associated_institutions=[],
        )
        AuthorInstitution.objects.create(
            author=applicant.author_profile,
            institution=institution,
            years=[],
        )
        self._contribute(self.user, fundraise, rsc=100)

        result = self.service.get_funding_overview(self.user)

        insts = result["supported_institutions"]
        self.assertEqual(len(insts), 1)
        self.assertEqual(insts[0]["id"], institution.id)
        self.assertEqual(insts[0]["display_name"], "Test University")
        self.assertEqual(insts[0]["type"], "education")

    def test_supported_institutions_dedupes_same_institution_across_pis(self):
        """Two funded proposals / two PIs linked to the same Institution appear once."""
        applicant1 = create_random_authenticated_user("pi_one")
        applicant2 = create_random_authenticated_user("pi_two")
        institution = Institution.objects.create(
            openalex_id="https://openalex.org/Sshared0001",
            ror_id="https://ror.org/00shared01",
            display_name="Shared Lab",
            type="facility",
            associated_institutions=[],
        )
        AuthorInstitution.objects.create(
            author=applicant1.author_profile,
            institution=institution,
            years=[],
        )
        AuthorInstitution.objects.create(
            author=applicant2.author_profile,
            institution=institution,
            years=[],
        )

        grant_post = create_post(created_by=self.user, document_type=GRANT_DOC_TYPE)
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_post.unified_document,
            amount=Decimal("2000"),
            status=Grant.OPEN,
        )

        proposal1 = create_post(created_by=applicant1, document_type=PREREGISTRATION)
        fr1 = Fundraise.objects.create(
            created_by=applicant1,
            unified_document=proposal1.unified_document,
            goal_amount=Decimal("500"),
            goal_currency="USD",
        )
        GrantApplication.objects.create(
            grant=grant,
            preregistration_post=proposal1,
            applicant=applicant1,
        )

        proposal2 = create_post(created_by=applicant2, document_type=PREREGISTRATION)
        fr2 = Fundraise.objects.create(
            created_by=applicant2,
            unified_document=proposal2.unified_document,
            goal_amount=Decimal("500"),
            goal_currency="USD",
        )
        GrantApplication.objects.create(
            grant=grant,
            preregistration_post=proposal2,
            applicant=applicant2,
        )

        self._contribute(self.user, fr1, rsc=50)
        self._contribute(self.user, fr2, rsc=50)

        result = self.service.get_funding_overview(self.user)

        self.assertEqual(len(result["supported_proposals"]), 2)
        self.assertEqual(len(result["supported_institutions"]), 1)
        self.assertEqual(result["supported_institutions"][0]["id"], institution.id)

    def test_supported_proposals_deduplicates_by_post(self):
        # Arrange
        applicant = create_random_authenticated_user("applicant")

        grant_post1 = create_post(created_by=self.user, document_type=GRANT_DOC_TYPE)
        grant1 = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_post1.unified_document,
            amount=Decimal("1000"),
            status=Grant.OPEN,
        )
        grant_post2 = create_post(created_by=self.user, document_type=GRANT_DOC_TYPE)
        grant2 = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_post2.unified_document,
            amount=Decimal("1000"),
            status=Grant.OPEN,
        )

        proposal_post = create_post(created_by=applicant, document_type=PREREGISTRATION)
        fundraise = Fundraise.objects.create(
            created_by=applicant,
            unified_document=proposal_post.unified_document,
            goal_amount=Decimal("500"),
            goal_currency="USD",
        )

        GrantApplication.objects.create(
            grant=grant1, preregistration_post=proposal_post, applicant=applicant
        )
        GrantApplication.objects.create(
            grant=grant2, preregistration_post=proposal_post, applicant=applicant
        )

        self._contribute(self.user, fundraise, rsc=100)

        # Act
        result = self.service.get_funding_overview(self.user)

        # Assert
        self.assertEqual(len(result["supported_proposals"]), 1)
        self.assertEqual(result["supported_institutions"], [])
        self.assertEqual(len(result["supported_proposals"]), 1)
        self.assertEqual(result["supported_institutions"], [])
