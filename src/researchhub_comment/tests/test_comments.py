import time

from rest_framework.test import APITestCase

from paper.tests.helpers import create_paper
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from user.tests.helpers import create_moderator, create_random_default_user, create_user


class CommentViewTests(APITestCase):
    def setUp(self):
        self.bank_user = create_user(email="bank@researchhub.com")
        self.paper_uploader = create_random_default_user("paper_uploader_1")
        self.user_1 = create_random_default_user("comment_user_1")
        self.user_2 = create_random_default_user("comment_user_2")
        self.user_3 = create_random_default_user("comment_user_3")
        self.user_4 = create_random_default_user("comment_user_4")
        self.moderator = create_moderator(first_name="moderator", last_name="moderator")
        self.paper = create_paper(uploaded_by=self.paper_uploader)

    def _create_comment(self, obj_name, obj_id, created_by, data):
        self.client.force_authenticate(created_by)
        res = self.client.post(
            f"/api/{obj_name}/{obj_id}/comments/create_rh_comment/", {**data}
        )
        return res

    def _create_comment_bounty(self, obj_name, obj_id, created_by, data):
        self.client.force_authenticate(created_by)
        res = self.client.post(
            f"/api/{obj_name}/{obj_id}/comments/create_comment_with_bounty/", {**data}
        )
        return res

    def _create_paper_comment(
        self, paper_id, created_by, text="this is a test comment", **kwargs
    ):
        res = self._create_comment(
            "paper",
            paper_id,
            created_by,
            {
                "comment_content_json": {"ops": [{"insert": text}]},
                **kwargs,
            },
        )
        return res

    def _create_paper_comment_with_bounty(
        self, paper_id, created_by, text="this is a test comment", amount=100, **kwargs
    ):
        res = self._create_comment_bounty(
            "paper",
            paper_id,
            created_by,
            {
                "comment_content_json": {"ops": [{"insert": text}]},
                "amount": amount,
                **kwargs,
            },
        )
        return res

    def _create_post_comment(
        self, post_id, created_by, text="this is a test comment", **kwargs
    ):
        self.client.force_authenticate(created_by)

        res = self._create_comment(
            "post",
            post_id,
            created_by,
            {
                "comment_content_json": {"ops": [{"insert": text}]},
                **kwargs,
            },
        )
        return res

    def test_comment_creator_can_edit(self):
        creator = self.user_1
        comment = self._create_paper_comment(self.paper.id, creator)
        self.client.force_authenticate(self.user_1)

        update_comment_res = self.client.patch(
            f"/api/paper/{self.paper.id}/comments/{comment.data['id']}/",
            {
                "comment_content_json": {
                    "ops": [{"insert": "this is an updated test comment"}]
                },
            },
        )

        self.assertEqual(update_comment_res.status_code, 200)
        return update_comment_res

    def test_non_comment_creator_cant_edit(self):
        creator = self.user_1
        comment = self._create_paper_comment(self.paper.id, creator)
        self.client.force_authenticate(self.user_2)

        update_comment_res = self.client.patch(
            f"/api/paper/{self.paper.id}/comments/{comment.data['id']}/",
            {
                "comment_content_json": {
                    "ops": [{"insert": "this is a failed updated test comment"}]
                },
            },
        )

        self.assertEqual(update_comment_res.status_code, 403)
        return update_comment_res

    def test_nested_discussion_counts(self):
        creator_1 = self.user_1
        creator_2 = self.user_2
        creator_3 = self.user_3
        parent_comment_1 = self._create_paper_comment(self.paper.id, creator_1)
        parent_comment_2 = self._create_paper_comment(self.paper.id, creator_2)
        comment_1 = self._create_paper_comment(
            self.paper.id, creator_3, parent_id=parent_comment_1.data["id"]
        )
        comment_2 = self._create_paper_comment(
            self.paper.id, creator_3, parent_id=parent_comment_2.data["id"]
        )
        comment_3 = self._create_paper_comment(
            self.paper.id, creator_3, parent_id=comment_2.data["id"]
        )
        comment_4 = self._create_paper_comment(
            self.paper.id, creator_3, parent_id=comment_3.data["id"]
        )
        comment_5 = self._create_paper_comment(
            self.paper.id, creator_1, parent_id=comment_4.data["id"]
        )
        comment_6 = self._create_paper_comment(
            self.paper.id, creator_2, parent_id=comment_5.data["id"]
        )

        res = self.client.get(f"/api/paper/{self.paper.id}/")

        self.assertEqual(comment_1.status_code, 200)
        self.assertEqual(comment_6.status_code, 200)
        self.assertEqual(res.data["discussion_count"], 8)

    def test_filter_by_reviews(self):
        review_creator = self.user_1
        regular_creator = self.user_2
        self._create_paper_comment(self.paper.id, review_creator, thread_type="REVIEW")
        self._create_paper_comment(self.paper.id, regular_creator)

        peer_review_res = self.client.get(
            f"/api/paper/{self.paper.id}/comments/?filtering=REVIEW&ordering=BEST&ascending=FALSE"
        )
        regular_res = self.client.get(
            f"/api/paper/{self.paper.id}/comments/?ordering=BEST&ascending=FALSE"
        )

        self.assertEqual(peer_review_res.status_code, 200)
        self.assertEqual(peer_review_res.data["count"], 1)
        self.assertEqual(regular_res.status_code, 200)
        self.assertEqual(regular_res.data["count"], 2)

    def test_filter_by_bounties(self):
        bounty_creator = self.user_1
        regular_creator = self.user_2
        review_creator = self.user_3
        distribution = Dist("REWARD", 1000000000, give_rep=False)

        distributor = Distributor(
            distribution, bounty_creator, bounty_creator, time.time(), bounty_creator
        )
        distributor.distribute()
        self._create_paper_comment_with_bounty(self.paper.id, bounty_creator)
        self._create_paper_comment_with_bounty(self.paper.id, bounty_creator)
        self._create_paper_comment(self.paper.id, regular_creator)
        self._create_paper_comment(self.paper.id, review_creator, thread_type="REVIEW")

        bounty_res = self.client.get(
            f"/api/paper/{self.paper.id}/comments/?filtering=BOUNTY&ordering=BEST&ascending=FALSE"
        )
        regular_res = self.client.get(
            f"/api/paper/{self.paper.id}/comments/?ordering=BEST&ascending=FALSE"
        )

        self.assertEqual(bounty_res.status_code, 200)
        self.assertEqual(bounty_res.data["count"], 2)
        self.assertEqual(regular_res.status_code, 200)
        self.assertEqual(regular_res.data["count"], 4)
