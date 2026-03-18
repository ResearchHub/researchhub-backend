from datetime import timedelta

from django.contrib.admin.options import get_content_type_for_model
from django.utils import timezone
from rest_framework.test import APITestCase

from discussion.constants.flag_reasons import SPAM
from paper.tests.helpers import create_paper
from reputation.models import Distribution
from researchhub_document.helpers import create_post
from user.tests.helpers import (
    create_hub_editor,
    create_random_authenticated_user,
    create_user,
)

AUTO_PAYMENTS_URL = "/api/audit/auto_payments/"
DISMISS_FLAGGED_CONTENT_URL = "/api/audit/dismiss_flagged_content/"
FLAG_AND_REMOVE_URL = "/api/audit/flag_and_remove/"
REMOVE_FLAGGED_CONTENT = "api/audit/remove_flagged_content/"


class AuditViewTests(APITestCase):
    def setUp(self):
        self.community_user = create_user(email="main@researchhub.foundation")
        self.random_content_creator = create_random_authenticated_user(
            "content_creator"
        )
        self.reg_user = create_random_authenticated_user("test_reg_user")
        [self.test_editor, self.test_editor_hub] = create_hub_editor(
            unique_value="test_editor", hub_name="test_editor", moderator=False
        )

    def test_can_flag_paper(self):
        target_paper = create_paper(uploaded_by=self.random_content_creator)

        self.client.force_authenticate(self.reg_user)
        http_response = self.client.post(
            f"/api/paper/{target_paper.id}/flag/", {"reason_choice": SPAM}
        )
        self.assertContains(http_response, "id", status_code=201)

    def test_can_flag_rh_post(self):
        target_post = create_post(created_by=self.random_content_creator)

        self.client.force_authenticate(self.reg_user)
        http_response = self.client.post(
            f"/api/researchhubpost/{target_post.id}/flag/", {"reason_choice": SPAM}
        )
        self.assertContains(http_response, "id", status_code=201)

    def test_can_flag_paper_with_reason_memo(self):
        target_paper = create_paper(uploaded_by=self.random_content_creator)

        self.client.force_authenticate(self.reg_user)
        memo = "Please review for spammy content."
        http_response = self.client.post(
            f"/api/paper/{target_paper.id}/flag/",
            {"reason_choice": SPAM, "reason_memo": memo},
        )
        self.assertContains(http_response, "id", status_code=201)
        self.assertEqual(http_response.data.get("reason_memo"), memo)

    def test_can_flag_rh_post_with_reason_memo(self):
        target_post = create_post(created_by=self.random_content_creator)

        self.client.force_authenticate(self.reg_user)
        memo = "Low quality and repetitive."
        http_response = self.client.post(
            f"/api/researchhubpost/{target_post.id}/flag/",
            {"reason_choice": SPAM, "reason_memo": memo},
        )
        self.assertContains(http_response, "id", status_code=201)
        self.assertEqual(http_response.data.get("reason_memo"), memo)

    def test_editor_can_bulk_flag_and_remove(self):
        target_paper = create_paper(uploaded_by=self.random_content_creator)

        self.client.force_authenticate(self.test_editor)
        http_response = self.client.post(
            FLAG_AND_REMOVE_URL,
            {
                "flag": [
                    {
                        "content_type": get_content_type_for_model(target_paper).id,
                        "object_id": target_paper.id,
                        "reason_choice": SPAM,
                        "reason_memo": "Coordinated spam network evidence.",
                    },
                ],
                "verdict": {
                    "verdict_choice": SPAM,
                    "is_content_removed": True,
                },
                "send_email": False,
            },
        )
        self.assertContains(http_response, "flag", status_code=200)
        self.assertContains(http_response, "verdict")
        self.assertEqual(
            http_response.data["flag"][0].get("reason_memo"),
            "Coordinated spam network evidence.",
        )

    def test_reg_user_cannot_bulk_flag_and_remove(self):
        target_paper = create_paper(uploaded_by=self.random_content_creator)

        self.client.force_authenticate(self.reg_user)
        http_response = self.client.post(
            FLAG_AND_REMOVE_URL,
            {
                "flag": [
                    {
                        "content_type": get_content_type_for_model(target_paper).id,
                        "object_id": target_paper.id,
                    },
                ],
                "verdict": {
                    "verdict_choice": SPAM,
                    "is_content_removed": True,
                },
                "send_email": False,
            },
        )
        self.assertEqual(http_response.status_code, 403)

    def test_editor_can_dismiss_flag(self):
        self.client.force_authenticate(self.test_editor)
        target_paper = create_paper(uploaded_by=self.random_content_creator)
        self.client.post(f"/api/paper/{target_paper.id}/flag/", {"reason_choice": SPAM})
        target_flag = target_paper.flags.first()

        http_response = self.client.post(
            DISMISS_FLAGGED_CONTENT_URL, {"flag_ids": [target_flag.id]}
        )
        self.assertEqual(http_response.status_code, 200)

    def test_reg_user_cannot_dismiss_flag(self):
        self.client.force_authenticate(self.reg_user)
        target_paper = create_paper(uploaded_by=self.random_content_creator)
        self.client.post(f"/api/paper/{target_paper.id}/flag/", {"reason_choice": SPAM})
        target_flag = target_paper.flags.first()

        http_response = self.client.post(
            DISMISS_FLAGGED_CONTENT_URL, {"flag_ids": [target_flag.id]}
        )
        self.assertEqual(http_response.status_code, 403)


class AutoPaymentAuditTests(APITestCase):
    def setUp(self):
        self.community_user = create_user(email="main@researchhub.foundation")
        self.recipient = create_random_authenticated_user("recipient_user")
        self.reg_user = create_random_authenticated_user("test_reg_user")
        [self.editor, self.editor_hub] = create_hub_editor(
            unique_value="auto_pay_editor",
            hub_name="auto_pay_hub",
            moderator=False,
        )

        self.editor_payout = Distribution.objects.create(
            recipient=self.recipient,
            amount=5000,
            distribution_type="EDITOR_PAYOUT",
        )
        self.editor_payout.set_distributed()

        self.author_reward = Distribution.objects.create(
            recipient=self.recipient,
            amount=2500,
            distribution_type="PREREGISTRATION_UPDATE_REWARD",
        )
        self.author_reward.set_distributed()

        Distribution.objects.create(
            recipient=self.recipient,
            amount=100,
            distribution_type="PURCHASE",
        )

    def test_editor_can_view_auto_payments(self):
        # Arrange
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.get(AUTO_PAYMENTS_URL)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        types = {r["distribution_type"] for r in response.data["results"]}
        self.assertEqual(types, {"EDITOR_PAYOUT", "PREREGISTRATION_UPDATE_REWARD"})

    def test_reg_user_cannot_view_auto_payments(self):
        # Arrange
        self.client.force_authenticate(self.reg_user)

        # Act
        response = self.client.get(AUTO_PAYMENTS_URL)

        # Assert
        self.assertEqual(response.status_code, 403)

    def test_filter_by_distribution_type(self):
        # Arrange
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.get(
            AUTO_PAYMENTS_URL, {"distribution_type": "EDITOR_PAYOUT"}
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["distribution_type"], "EDITOR_PAYOUT"
        )

    def test_filter_by_recipient(self):
        # Arrange
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.get(
            AUTO_PAYMENTS_URL, {"recipient": self.recipient.id}
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)

    def test_response_includes_recipient_info(self):
        # Arrange
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.get(AUTO_PAYMENTS_URL)

        # Assert
        result = response.data["results"][0]
        self.assertIn("recipient", result)
        self.assertIn("id", result["recipient"])
        self.assertIn("first_name", result["recipient"])
        self.assertIn("author_profile", result["recipient"])

    def test_filter_by_date_range_includes_recent(self):
        # Arrange
        self.client.force_authenticate(self.editor)
        one_hour_ago = (timezone.now() - timedelta(hours=1)).isoformat()

        # Act
        response = self.client.get(
            AUTO_PAYMENTS_URL, {"created_after": one_hour_ago}
        )

        # Assert
        self.assertEqual(response.data["count"], 2)

    def test_filter_by_date_range_excludes_old(self):
        # Arrange
        self.client.force_authenticate(self.editor)
        one_hour_from_now = (timezone.now() + timedelta(hours=1)).isoformat()

        # Act
        response = self.client.get(
            AUTO_PAYMENTS_URL, {"created_after": one_hour_from_now}
        )

        # Assert
        self.assertEqual(response.data["count"], 0)
