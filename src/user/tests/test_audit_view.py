from django.contrib.admin.options import get_content_type_for_model
from rest_framework.test import APITestCase

from discussion.constants.flag_reasons import SPAM
from paper.tests.helpers import create_paper
from researchhub_document.helpers import create_hypothesis, create_post
from user.tests.helpers import (
    create_hub_editor,
    create_random_authenticated_user,
    create_user,
)

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

    def test_can_flag_hypothesis(self):
        target_hypothesis = create_hypothesis(created_by=self.random_content_creator)

        self.client.force_authenticate(self.reg_user)
        http_response = self.client.post(
            f"/api/hypothesis/{target_hypothesis.id}/flag/", {"reason_choice": SPAM}
        )
        self.assertContains(http_response, "id", status_code=201)

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
            f"/api/researchhub_post/{target_post.id}/flag/", {"reason_choice": SPAM}
        )
        self.assertContains(http_response, "id", status_code=201)

    def test_editor_can_bulk_flag_and_remove(self):
        target_hypothesis = create_hypothesis(created_by=self.random_content_creator)
        target_paper = create_paper(uploaded_by=self.random_content_creator)

        self.client.force_authenticate(self.test_editor)
        http_response = self.client.post(
            FLAG_AND_REMOVE_URL,
            {
                "flag": [
                    {
                        "content_type": get_content_type_for_model(
                            target_hypothesis
                        ).id,
                        "object_id": target_hypothesis.id,
                    },
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
        self.assertContains(http_response, "flag", status_code=200)
        self.assertContains(http_response, "verdict")

    def test_reg_user_cannot_bulk_flag_and_remove(self):
        target_hypothesis = create_hypothesis(created_by=self.random_content_creator)
        target_paper = create_paper(uploaded_by=self.random_content_creator)

        self.client.force_authenticate(self.reg_user)
        http_response = self.client.post(
            FLAG_AND_REMOVE_URL,
            {
                "flag": [
                    {
                        "content_type": get_content_type_for_model(
                            target_hypothesis
                        ).id,
                        "object_id": target_hypothesis.id,
                    },
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
        self.assertEquals(http_response.status_code, 403)

    def test_editor_can_dismiss_flag(self):
        self.client.force_authenticate(self.test_editor)
        target_paper = create_paper(uploaded_by=self.random_content_creator)
        self.client.post(f"/api/paper/{target_paper.id}/flag/", {"reason_choice": SPAM})
        target_flag = target_paper.flags.first()

        http_response = self.client.post(
            DISMISS_FLAGGED_CONTENT_URL, {"flag_ids": [target_flag.id]}
        )
        self.assertEquals(http_response.status_code, 200)

    def test_reg_user_cannot_dismiss_flag(self):
        self.client.force_authenticate(self.reg_user)
        target_paper = create_paper(uploaded_by=self.random_content_creator)
        self.client.post(f"/api/paper/{target_paper.id}/flag/", {"reason_choice": SPAM})
        target_flag = target_paper.flags.first()

        http_response = self.client.post(
            DISMISS_FLAGGED_CONTENT_URL, {"flag_ids": [target_flag.id]}
        )
        self.assertEquals(http_response.status_code, 403)
