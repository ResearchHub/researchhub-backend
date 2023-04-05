from rest_framework.test import APITestCase

from paper.tests.helpers import create_paper
from user.tests.helpers import create_moderator, create_random_default_user


class CommentViewTests(APITestCase):
    def setUp(self):
        self.user_1 = create_random_default_user("comment_user_1")
        self.user_2 = create_random_default_user("comment_user_2")
        self.user_3 = create_random_default_user("comment_user_3")
        self.user_4 = create_random_default_user("comment_user_4")
        self.moderator = create_moderator(first_name="moderator", last_name="moderator")
        self.paper = create_paper()

    def _create_comment(self, obj_name, obj_id, created_by, data):
        self.client.force_authenticate(created_by)
        res = self.client.post(
            f"/api/{obj_name}/{obj_id}/comments/create_rh_comment/", {**data}
        )
        return res

    def _create_paper_comment(self, paper_id, created_by, *args, **kwargs):
        res = self.create_comment(
            "paper",
            paper_id,
            created_by,
            {
                "comment_content_json": {"ops": [{"insert": "this is a test comment"}]},
            },
        )
        return res

    def _create_post_comment(self, post_id, created_by, *args, **kwargs):
        self.client.force_authenticate(created_by)

        res = self.create_comment(
            "post",
            post_id,
            created_by,
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
