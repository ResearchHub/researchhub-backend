import time
from datetime import datetime

from rest_framework.test import APITestCase

from discussion.tests.helpers import create_rh_comment
from paper.tests.helpers import create_paper
from user.models import User
from user.tests.helpers import create_moderator, create_random_default_user, create_user


class CommentViewTests(APITestCase):
    def setUp(self):
        self.user_1 = create_random_default_user("comment_user_1")
        self.user_2 = create_random_default_user("comment_user_2")
        self.user_3 = create_random_default_user("comment_user_3")
        self.user_4 = create_random_default_user("comment_user_4")
        self.moderator = create_moderator(first_name="moderator", last_name="moderator")
        self.paper = create_paper()

    def _create_comment(self, created_by, *args, **kwargs):
        self.client.force_authenticate(created_by)

        self.client.post("/api/paper/123/comments/create_rh_comment/")

    def _create_paper_comment(self, paper_id, created_by, *args, **kwargs):
        self.client.force_authenticate(created_by)

        res = self.client.post(
            f"/api/paper/{paper_id}/comments/create_rh_comment/",
            {
                "comment_content_json": {"ops": [{"insert": "this is a test comment"}]},
            },
        )
        return res

    def test_comment_creator_can_edit(self):
        creator = self.user_1
        comment = self._create_paper_comment(self.paper.id, creator)
        self.client.force_authenticate(self.user_1)

        update_comment_res = self.client.patch(
            f"/api/paper/{self.paper.id}/comments/f{comment.data['id']}/",
            {
                "comment_content_json": {
                    "ops": [{"insert": "this is an updated test comment"}]
                },
            },
        )

        self.assertEqual(update_comment_res.status_code, 200)
        return update_comment_res
