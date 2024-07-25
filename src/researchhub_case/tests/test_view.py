from rest_framework.test import APITestCase

from paper.tests.helpers import create_paper
from researchhub_case.constants.case_constants import PAPER_CLAIM
from researchhub_case.models import AuthorClaimCase
from user.tests.helpers import create_moderator, create_random_default_user


class ViewTests(APITestCase):
    def setUp(self):
        self.paper = create_paper(
            title="some title",
            uploaded_by=None,
            raw_authors='[{"first_name": "jane", "last_name": "smith"}]',
        )
        self.moderator = create_moderator(first_name="moderator", last_name="moderator")

    def _create_paper_claim_via_api(self, claiming_user):
        claiming_user = create_random_default_user("claiming_user")
        self.client.force_authenticate(claiming_user)

        paper = create_paper(
            title="some title",
            uploaded_by=None,
        )

        response = self.client.post(
            "/api/author_claim_case/",
            {
                "case_type": "PAPER_CLAIM",
                "creator": claiming_user.id,
                "requestor": claiming_user.id,
                "provided_email": "example@example.com",
                "target_paper_id": paper.id,
                "target_author_name": "some paper author",
            },
        )

        return response, paper

    def _get_open_claims(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get("/api/author_claim_case/moderator/?case_status=OPEN")

        return response

    def test_submit_paper_claim_shows_up_in_mod_dashboard(self):
        claiming_user = create_random_default_user("claiming_user")

        claim_create_response, paper = self._create_paper_claim_via_api(claiming_user)
        open_claims_response = self._get_open_claims()

        claim = open_claims_response.data["results"][0]
        self.assertEqual(claim["status"], "OPEN")
        self.assertEqual(open_claims_response.data["count"], 1)

    def test_only_verified_users_can_submit_claim(self):
        pass

    def test_approving_claim_pays_rewards_to_user(self):
        pass

    def test_rejecting_claim_does_not_pay_rewards_to_user(self):
        pass

    def test_only_mods_can_view_claims(self):
        pass
