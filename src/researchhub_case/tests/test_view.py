from rest_framework.test import APITestCase

from notification.models import Notification
from paper.tests.helpers import create_paper
from researchhub_case.constants.case_constants import PAPER_CLAIM
from researchhub_case.models import AuthorClaimCase
from user.related_models.user_verification_model import UserVerification
from user.tests.helpers import create_moderator, create_random_default_user


class ViewTests(APITestCase):
    def setUp(self):
        self.paper = create_paper(
            title="some title",
            uploaded_by=None,
            raw_authors='[{"first_name": "jane", "last_name": "smith"}]',
        )
        self.moderator = create_moderator(first_name="moderator", last_name="moderator")
        self.verified_user = create_random_default_user("verified user")
        self.unverified_user = create_random_default_user("UNVERIFIED USER")

        o = UserVerification.objects.create(
            user=self.verified_user,
            status=UserVerification.Status.APPROVED,
        )

        self.verified_user.refresh_from_db()

    def _approve_claim_via_api(self, case_id):
        self.client.force_authenticate(self.moderator)
        return self.client.post(
            "/api/author_claim_case/moderator/",
            {
                "case_id": case_id,
                "notify_user": True,
                "update_status": "APPROVED",
            },
        )

    def _create_paper_claim_via_api(self, claiming_user):
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
                "preregistration_url": "https://preregistration.example.com",
                "open_data_url": "https://opendata.example.com",
            },
        )

        return response, paper

    def _get_open_claims(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get("/api/author_claim_case/moderator/?case_status=OPEN")

        return response

    def test_submit_paper_claim_shows_up_in_mod_dashboard(self):
        claim_create_response, paper = self._create_paper_claim_via_api(
            self.verified_user
        )
        open_claims_response = self._get_open_claims()

        claim = open_claims_response.data["results"][0]
        self.assertEqual(claim["status"], "OPEN")
        self.assertEqual(open_claims_response.data["count"], 1)

    def test_unverified_users_cannot_submit_claim(self):
        claim_create_response, paper = self._create_paper_claim_via_api(
            self.unverified_user
        )

        self.assertEqual(claim_create_response.status_code, 403)

    def test_mod_can_approve_claim(self):
        claim_create_response, paper = self._create_paper_claim_via_api(
            self.verified_user
        )
        approve_response = self._approve_claim_via_api(claim_create_response.data["id"])
        self.assertEqual(approve_response.data["status"], "APPROVED")

    def test_preregistration_url_available(self):
        claim_create_response, paper = self._create_paper_claim_via_api(
            self.verified_user
        )
        self.assertEqual(
            claim_create_response.data["preregistration_url"],
            "https://preregistration.example.com",
        )

    def test_opendata_url_available(self):
        claim_create_response, paper = self._create_paper_claim_via_api(
            self.verified_user
        )
        self.assertEqual(
            claim_create_response.data["open_data_url"], "https://opendata.example.com"
        )

    def test_notifiy_user_after_claim_is_approved(self):
        claim_create_response, paper = self._create_paper_claim_via_api(
            self.verified_user
        )
        approve_response = self._approve_claim_via_api(claim_create_response.data["id"])

        notification = Notification.objects.filter(
            recipient=self.verified_user,
            notification_type=Notification.PAPER_CLAIM_PAYOUT,
        )

        self.assertEqual(notification.exists(), True)

    def test_approving_claim_pays_rewards_to_user(self):
        ## Fixme: @kouts to implement
        pass

    def test_rejecting_claim_does_not_pay_rewards_to_user(self):
        ## Fixme: @kouts to implement
        pass
