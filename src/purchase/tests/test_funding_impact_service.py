from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from hub.models import Hub
from institution.models import Institution
from purchase.models import Fundraise, Grant, GrantApplication, Purchase
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.usd_fundraise_contribution_model import UsdFundraiseContribution
from purchase.services.funding_impact_service import FundingImpactService, MILESTONES, UPDATE_BUCKETS
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT as GRANT_DOC_TYPE, PREREGISTRATION
from user.related_models.author_institution import AuthorInstitution
from user.tests.helpers import create_random_authenticated_user


class TestFundingImpactService(TestCase):
    def setUp(self):
        self.service = FundingImpactService()
        self.grant_creator = create_random_authenticated_user("grant_creator")
        self.researcher = create_random_authenticated_user("researcher")
        RscExchangeRate.objects.create(rate=0.5, real_rate=0.5, price_source="COIN_GECKO", target_currency="USD")
        self.fundraise_ct = ContentType.objects.get_for_model(Fundraise)

    def _create_grant(self, created_by=None):
        """Create a grant owned by the specified user."""
        creator = created_by or self.grant_creator
        post = create_post(created_by=creator, document_type=GRANT_DOC_TYPE)
        return Grant.objects.create(created_by=creator, unified_document=post.unified_document, amount=Decimal("10000"), status=Grant.OPEN)

    def _create_proposal_for_grant(self, grant, created_by=None):
        """Create a proposal (fundraise) that applied to the given grant."""
        creator = created_by or self.researcher
        post = create_post(created_by=creator, document_type=PREREGISTRATION)
        fundraise = Fundraise.objects.create(created_by=creator, unified_document=post.unified_document, goal_amount=Decimal("1000"), goal_currency="USD")
        GrantApplication.objects.create(grant=grant, preregistration_post=post, applicant=creator)
        return fundraise

    def _contribute(self, user, fundraise, rsc=0, usd_cents=0):
        if rsc:
            Purchase.objects.create(user=user, content_type=self.fundraise_ct, object_id=fundraise.id, purchase_type=Purchase.FUNDRAISE_CONTRIBUTION, purchase_method=Purchase.OFF_CHAIN, amount=str(rsc))
        if usd_cents:
            UsdFundraiseContribution.objects.create(user=user, fundraise=fundraise, amount_cents=usd_cents, fee_cents=0)

    def test_empty_response_for_new_user(self):
        # Act
        result = self.service.get_funding_impact(self.grant_creator)

        # Assert
        self.assertEqual(result["milestones"], {k: {"current": 0, "target": v[0]} for k, v in MILESTONES.items()})
        self.assertEqual(len(result["funding_over_time"]), 6)
        self.assertTrue(all(m["user_contributions"] == 0 for m in result["funding_over_time"]))
        self.assertEqual(result["topic_breakdown"], [])
        self.assertEqual(result["update_frequency"], [{"bucket": b, "count": 0} for b in UPDATE_BUCKETS])
        self.assertEqual(result["institutions_supported"], [])

    def test_milestones_calculate_correctly(self):
        # Arrange
        researcher2 = create_random_authenticated_user("researcher2")
        other = create_random_authenticated_user("other")
        grant = self._create_grant()
        f1 = self._create_proposal_for_grant(grant, self.researcher)
        f2 = self._create_proposal_for_grant(grant, researcher2)
        self._contribute(self.grant_creator, f1, rsc=100, usd_cents=5000)  # $50 + $50 = $100
        self._contribute(self.grant_creator, f2, rsc=100)  # $50
        self._contribute(other, f1, rsc=200)  # $100 matched

        # Act
        result = self.service.get_funding_impact(self.grant_creator)

        # Assert
        self.assertEqual(result["milestones"]["funding_contributed"], {"current": 150.0, "target": 500})
        self.assertEqual(result["milestones"]["researchers_supported"], {"current": 2, "target": 3})
        self.assertEqual(result["milestones"]["matched_funding"], {"current": 100.0, "target": 500})

    def test_funding_over_time_returns_6_months_cumulative(self):
        # Arrange
        grant = self._create_grant()
        fundraise = self._create_proposal_for_grant(grant)
        other = create_random_authenticated_user("other")
        self._contribute(self.grant_creator, fundraise, rsc=100)
        self._contribute(other, fundraise, rsc=200)

        # Act
        result = self.service.get_funding_impact(self.grant_creator)

        # Assert - always 6 months, YYYY-MM format, cumulative values
        self.assertEqual(len(result["funding_over_time"]), 6)
        self.assertRegex(result["funding_over_time"][0]["month"], r"^\d{4}-\d{2}$")
        self.assertEqual(result["funding_over_time"][5]["user_contributions"], 50.0)
        self.assertEqual(result["funding_over_time"][5]["matched_contributions"], 100.0)

    def test_topic_breakdown_groups_and_sorts(self):
        # Arrange
        hub1, hub2 = Hub.objects.create(name="Small"), Hub.objects.create(name="Big")
        grant = self._create_grant()
        f1 = self._create_proposal_for_grant(grant)
        f2 = self._create_proposal_for_grant(grant)
        f1.unified_document.hubs.add(hub1)
        f2.unified_document.hubs.add(hub2)
        self._contribute(self.grant_creator, f1, rsc=100)  # $50
        self._contribute(self.grant_creator, f2, rsc=400)  # $200

        # Act
        result = self.service.get_funding_impact(self.grant_creator)

        # Assert
        self.assertEqual(result["topic_breakdown"][0], {"name": "Big", "amount_usd": 200.0})
        self.assertEqual(result["topic_breakdown"][1], {"name": "Small", "amount_usd": 50.0})

    def test_update_frequency_buckets(self):
        # Arrange - create 4 proposals with 0, 1, 2, and 5 updates to cover all bucket branches
        grant = self._create_grant()
        r1, r2, r3, r4 = [create_random_authenticated_user(f"r{i}") for i in range(4)]
        f0 = self._create_proposal_for_grant(grant, r1)  # 0 updates
        f1 = self._create_proposal_for_grant(grant, r2)  # 1 update
        f2 = self._create_proposal_for_grant(grant, r3)  # 2 updates (2-3 bucket)
        f4 = self._create_proposal_for_grant(grant, r4)  # 5 updates (4+ bucket)
        for f in [f0, f1, f2, f4]:
            self._contribute(self.grant_creator, f, rsc=100)

        for f, count in [(f1, 1), (f2, 2), (f4, 5)]:
            post = f.unified_document.posts.first()
            thread = RhCommentThreadModel.objects.create(thread_type=AUTHOR_UPDATE, content_object=post, created_by=f.created_by)
            for _ in range(count):
                RhCommentModel.objects.create(thread=thread, created_by=f.created_by, comment_content_json={}, comment_type=AUTHOR_UPDATE)

        # Act
        result = self.service.get_funding_impact(self.grant_creator)

        # Assert - all bucket branches covered
        buckets = {b["bucket"]: b["count"] for b in result["update_frequency"]}
        self.assertEqual(buckets, {"0": 1, "1": 1, "2-3": 1, "4+": 1})

    def test_institutions_supported_with_split(self):
        # Arrange - covers all continue branches: no amount, no author_profile, no institutions
        inst1 = Institution.objects.create(openalex_id="I1", ror_id="R1", display_name="Uni A", type="edu", region="CA", country_code="US", associated_institutions=[])
        inst2 = Institution.objects.create(openalex_id="I2", ror_id="R2", display_name="Uni B", type="edu", associated_institutions=[])
        AuthorInstitution.objects.create(author=self.researcher.author_profile, institution=inst1)
        AuthorInstitution.objects.create(author=self.researcher.author_profile, institution=inst2)
        grant = self._create_grant()
        fundraise = self._create_proposal_for_grant(grant)
        self._contribute(self.grant_creator, fundraise, rsc=100)  # $50 split = $25 each

        # Add fundraise with no contribution (covers `if not amount: continue`)
        r2 = create_random_authenticated_user("r2")
        self._create_proposal_for_grant(grant, r2)

        # Add fundraise where researcher has no institutions (covers `if not author_institutions: continue`)
        r3 = create_random_authenticated_user("r3")
        f_no_inst = self._create_proposal_for_grant(grant, r3)
        self._contribute(self.grant_creator, f_no_inst, rsc=50)

        # Act
        result = self.service.get_funding_impact(self.grant_creator)

        # Assert - only the 2 institutions from first fundraise should appear
        self.assertEqual(len(result["institutions_supported"]), 2)
        inst_a = next(i for i in result["institutions_supported"] if i["name"] == "Uni A")
        self.assertEqual(inst_a["location"], "CA, US")
        self.assertEqual(inst_a["amount_usd"], 25.0)
        self.assertEqual(inst_a["project_count"], 1)
