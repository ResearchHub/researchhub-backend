import json
import os
from unittest.mock import patch

from django.conf import settings
from rest_framework.test import APITestCase

from notification.models import Notification
from paper.models import Paper
from paper.openalex_util import process_openalex_works
from paper.related_models.authorship_model import Authorship
from paper.tests.helpers import create_paper
from reputation.related_models.paper_reward import HubCitationValue, PaperReward
from user.related_models.user_verification_model import UserVerification
from user.tests.helpers import create_moderator, create_random_default_user
from utils.openalex import OpenAlex


class ViewTests(APITestCase):
    @patch.object(OpenAlex, "get_authors")
    def setUp(self, mock_get_authors):
        self.moderator = create_moderator(first_name="moderator", last_name="moderator")
        self.verified_user = create_random_default_user("verified user")
        self.unverified_user = create_random_default_user("UNVERIFIED USER")

        works_file_path = os.path.join(
            settings.BASE_DIR, "paper", "tests", "openalex_works.json"
        )
        with open(works_file_path, "r") as file:
            response = json.load(file)
            self.works = response.get("results")

        authors_file_path = os.path.join(
            settings.BASE_DIR, "paper", "tests", "openalex_authors.json"
        )
        with open(authors_file_path, "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(self.works)

            dois = [work.get("doi") for work in self.works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]
            created_papers = Paper.objects.filter(doi__in=dois).order_by("citations")
            self.paper = created_papers[0]

        HubCitationValue.objects.create(
            hub=self.paper.unified_document.get_primary_hub(),
            variables={
                "citations": {
                    "bins": {
                        json.dumps((1, 1000000)): json.dumps(
                            {
                                "slope": 0.32872014059165,
                                "intercept": -0.0567277429812658,
                            }
                        )
                    }
                }
            },
        )

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

    def _reject_claim_via_api(self, case_id):
        self.client.force_authenticate(self.moderator)
        return self.client.post(
            "/api/author_claim_case/moderator/",
            {
                "case_id": case_id,
                "notify_user": True,
                "update_status": "DENIED",
            },
        )

    def _create_paper_claim_via_api(self, claiming_user, paper=None, authorship=None):
        self.client.force_authenticate(claiming_user)

        if not paper:
            paper = create_paper(
                title="some title",
                uploaded_by=None,
            )

        if not authorship:
            authorship = Authorship.objects.create(
                author=claiming_user.author_profile,
                author_position="first",
                raw_author_name="claiming user",
                paper=paper,
            )

        response = self.client.post(
            "/api/author_claim_case/",
            {
                "case_type": "PAPER_CLAIM",
                "creator": claiming_user.id,
                "requestor": claiming_user.id,
                "target_paper_id": paper.id,
                "authorship_id": authorship.id,
                "preregistration_url": "https://preregistration.example.com",
                "open_data_url": "https://opendata.example.com",
            },
        )

        return response, paper, authorship

    def _get_open_claims(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get("/api/author_claim_case/moderator/?case_status=OPEN")

        return response

    def test_same_user_cannot_submit_multiple_claims_for_same_paper(self):
        claim_create_response, paper, authorship = self._create_paper_claim_via_api(
            self.verified_user
        )

        claim_create_response2, _, _ = self._create_paper_claim_via_api(
            self.verified_user,
            paper,
            authorship,
        )

        self.assertEqual(claim_create_response2.status_code, 400)

    def test_same_user_can_submit_new_claim_if_rejected(self):
        claim_create_response, paper, authorship = self._create_paper_claim_via_api(
            self.verified_user, self.paper
        )

        self._reject_claim_via_api(claim_create_response.data["id"])

        claim_create_response2, _, _ = self._create_paper_claim_via_api(
            self.verified_user,
            paper,
            authorship,
        )

        self.assertEqual(claim_create_response2.status_code, 201)

    def test_user_cannot_submit_claim_for_paper_already_approved_claim(self):
        claim_create_response, paper, authorship = self._create_paper_claim_via_api(
            self.verified_user, self.paper
        )

        self._approve_claim_via_api(claim_create_response.data["id"])

        claim_create_response2, _, _ = self._create_paper_claim_via_api(
            self.verified_user,
            paper,
            authorship,
        )

        self.assertEqual(claim_create_response2.status_code, 400)

    def test_submit_paper_claim_shows_up_in_mod_dashboard(self):
        claim_create_response, paper, _ = self._create_paper_claim_via_api(
            self.verified_user, self.paper
        )

        open_claims_response = self._get_open_claims()

        claim = open_claims_response.data["results"][0]
        self.assertEqual(claim["status"], "OPEN")
        self.assertEqual(claim["paper"]["id"], paper.id)
        self.assertEqual(
            claim["paper"]["primary_hub"], paper.unified_document.get_primary_hub().name
        )
        self.assertEqual(open_claims_response.data["count"], 1)

    def test_unverified_users_cannot_submit_claim(self):
        claim_create_response, paper, _ = self._create_paper_claim_via_api(
            self.unverified_user
        )

        self.assertEqual(claim_create_response.status_code, 403)

    def test_mod_can_approve_claim(self):
        claim_create_response, paper, _ = self._create_paper_claim_via_api(
            self.verified_user, self.paper
        )
        approve_response = self._approve_claim_via_api(claim_create_response.data["id"])
        self.assertEqual(approve_response.data["status"], "APPROVED")

    def test_preregistration_url_available(self):
        claim_create_response, paper, _ = self._create_paper_claim_via_api(
            self.verified_user, self.paper
        )
        self.assertEqual(
            claim_create_response.data["preregistration_url"],
            "https://preregistration.example.com",
        )

    def test_opendata_url_available(self):
        claim_create_response, paper, _ = self._create_paper_claim_via_api(
            self.verified_user, self.paper
        )
        self.assertEqual(
            claim_create_response.data["open_data_url"], "https://opendata.example.com"
        )

    def test_notify_user_after_claim_is_approved(self):
        claim_create_response, paper, _ = self._create_paper_claim_via_api(
            self.verified_user, self.paper
        )
        approve_response = self._approve_claim_via_api(claim_create_response.data["id"])

        notification = Notification.objects.filter(
            recipient=self.verified_user,
            notification_type=Notification.PAPER_CLAIM_PAYOUT,
        )

        self.assertEqual(notification.exists(), True)

    def test_ensure_new_claims_have_version_2(self):
        claim_create_response, paper, _ = self._create_paper_claim_via_api(
            self.verified_user, self.paper
        )

        self.assertEqual(claim_create_response.data["version"], 2)
        self.assertIsNotNone(claim_create_response.data["paper_reward"])

    def test_approving_claim_pays_rewards_to_user(self):
        claim_create_response, paper, _ = self._create_paper_claim_via_api(
            self.verified_user, self.paper
        )
        self._approve_claim_via_api(claim_create_response.data["id"])

        paper_reward = PaperReward.objects.get(
            paper=paper, author=self.verified_user.author_profile
        )
        self.assertEqual(paper_reward.rsc_value, 43.77609099046774 * 5.0)
        self.assertIsNotNone(paper_reward.distribution)

    def test_rejecting_claim_does_not_pay_rewards_to_user(self):
        claim_create_response, paper, _ = self._create_paper_claim_via_api(
            self.verified_user, self.paper
        )
        self._reject_claim_via_api(claim_create_response.data["id"])

        paper_reward = PaperReward.objects.get(
            paper=paper, author=self.verified_user.author_profile
        )
        self.assertEqual(paper_reward.rsc_value, 43.77609099046774 * 5.0)
        self.assertIsNone(paper_reward.distribution)
