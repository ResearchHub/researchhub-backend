import time

from rest_framework.test import APITestCase

from hub.models import Hub
from notification.models import Notification
from paper.tests.helpers import create_paper
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import AlgorithmVariables, Score, ScoreChange
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

    def _give_rsc(self, user, amount):
        distribution = Dist("REWARD", amount, give_rep=False)
        distributor = Distributor(distribution, user, user, time.time(), user)
        distributor.distribute()

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
            "researchhubpost",
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
        self._create_paper_comment(
            self.paper.id, review_creator, thread_type="REVIEW", comment_type="REVIEW"
        )
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

    def test_html_content_format(self):
        """Test that HTML format comments store content in html field and not in comment_content_json"""
        html_content = "<p>This is a test HTML comment</p>"
        res = self._create_paper_comment(
            self.paper.id,
            self.user_1,
            content_format="HTML",
            comment_content=html_content,
        )

        self.assertEqual(res.status_code, 200)
        comment_data = res.data

        # Verify html field is set and comment_content_json is null
        self.assertEqual(comment_data["html"], html_content)
        self.assertIsNone(comment_data["comment_content_json"])

    def test_quill_content_format(self):
        """Test that QUILL_EDITOR format comments store content in comment_content_json field and not in html"""
        quill_content = {"ops": [{"insert": "This is a test Quill comment"}]}
        res = self._create_paper_comment(
            self.paper.id, self.user_1, comment_content_json=quill_content
        )

        self.assertEqual(res.status_code, 200)
        comment_data = res.data

        # Verify comment_content_json is set and html is null
        self.assertEqual(comment_data["comment_content_json"], quill_content)
        self.assertIsNone(comment_data["html"])

    def test_comment_mentions(self):
        creator = self.user_1
        recipient = self.user_2
        self._create_paper_comment(self.paper.id, creator, mentions=[self.user_2.id])
        self.client.force_authenticate(recipient)

        notification_res = self.client.get("/api/notification/")

        self.assertEqual(notification_res.status_code, 200)
        self.assertEqual(notification_res.data["count"], 1)

    def test_notify_qualified_users_about_bounty(self):

        user1_with_expertise = create_random_default_user("user_with_expertise")
        hub = Hub.objects.create(name="test_hub")

        score = Score.objects.create(
            hub=hub,
            author=user1_with_expertise.author_profile,
            score=100,
        )

        self._give_rsc(self.user_1, 1000000)

        response = self._create_paper_comment_with_bounty(
            self.paper.id,
            self.user_1,
            text="this is a test comment",
            amount=100,
            target_hub_ids=[hub.id],
        )

        notification = Notification.objects.filter(
            recipient=user1_with_expertise
        ).last()

        self.assertEqual(notification.notification_type, Notification.BOUNTY_FOR_YOU)

    def test_do_not_notify_unqualified_users_about_bounty(self):

        user1_with_expertise = create_random_default_user("user_with_expertise")
        hub = Hub.objects.create(name="test_hub")

        score = Score.objects.create(
            hub=hub,
            author=user1_with_expertise.author_profile,
            score=90,
        )

        self._give_rsc(self.user_1, 1000000)

        self._create_paper_comment_with_bounty(
            self.paper.id,
            self.user_1,
            text="this is a test comment",
            amount=120,
            target_hub_ids=[hub.id],
        )

        notification = Notification.objects.filter(recipient=user1_with_expertise)

        self.assertEqual(notification.exists(), False)

    def test_censor_paper_comments_updates_discussion_count(self):
        # Create a parent comment with multiple children
        parent_comment = self._create_paper_comment(self.paper.id, self.user_1)
        child1 = self._create_paper_comment(
            self.paper.id, self.user_2, parent_id=parent_comment.data["id"]
        )
        child2 = self._create_paper_comment(
            self.paper.id, self.user_3, parent_id=parent_comment.data["id"]
        )

        # Verify initial discussion count
        paper_res = self.client.get(f"/api/paper/{self.paper.id}/")
        initial_count = paper_res.data["discussion_count"]
        self.assertEqual(initial_count, 3)

        # Censor parent comment
        self.client.force_authenticate(self.moderator)
        censor_res = self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{parent_comment.data['id']}/censor/"
        )

        # Verify discussion count was reduced by 3 (parent + 2 children)
        paper_res = self.client.get(f"/api/paper/{self.paper.id}/")
        self.assertEqual(paper_res.data["discussion_count"], 0)

    def test_censor_child_with_deleted_parent_preserves_count(self):
        # Create a comment chain: parent -> child1 -> child2
        parent_comment = self._create_paper_comment(self.paper.id, self.user_1)
        child1 = self._create_paper_comment(
            self.paper.id, self.user_2, parent_id=parent_comment.data["id"]
        )
        child2 = self._create_paper_comment(
            self.paper.id, self.user_3, parent_id=child1.data["id"]
        )

        # Get initial count
        paper_res = self.client.get(f"/api/paper/{self.paper.id}/")
        initial_count = paper_res.data["discussion_count"]
        self.assertEqual(initial_count, 3)

        # Censor parent first
        self.client.force_authenticate(self.moderator)
        self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{parent_comment.data['id']}/censor/"
        )

        # Verify count reduced by 3
        paper_res = self.client.get(f"/api/paper/{self.paper.id}/")
        self.assertEqual(paper_res.data["discussion_count"], 0)

        # Now censor child2 - this shouldn't change the count since parent is already censored
        censor_res = self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{child2.data['id']}/censor/"
        )

        paper_res = self.client.get(f"/api/paper/{self.paper.id}/")
        self.assertEqual(paper_res.data["discussion_count"], 0)

    def test_censor_nested_comments(self):
        # Create a deeply nested chain of comments
        parent = self._create_paper_comment(self.paper.id, self.user_1)
        child1 = self._create_paper_comment(
            self.paper.id, self.user_2, parent_id=parent.data["id"]
        )
        child2 = self._create_paper_comment(
            self.paper.id, self.user_3, parent_id=child1.data["id"]
        )
        child3 = self._create_paper_comment(
            self.paper.id, self.user_4, parent_id=child2.data["id"]
        )

        # Verify initial count
        paper_res = self.client.get(f"/api/paper/{self.paper.id}/")
        self.assertEqual(paper_res.data["discussion_count"], 4)

        # Censor child2 (middle of chain)
        self.client.force_authenticate(self.moderator)
        self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{child2.data['id']}/censor/"
        )

        # Should reduce count by 2 (child2 and child3)
        paper_res = self.client.get(f"/api/paper/{self.paper.id}/")
        self.assertEqual(paper_res.data["discussion_count"], 2)

    def test_censor_post_comments_updates_discussion_count(self):
        # Create a post first
        self.client.force_authenticate(self.user_1)
        post_res = self.client.post(
            "/api/researchhubpost/",
            {
                "title": "Test Post needs to be 20 characters long",
                "content_json": {
                    "ops": [
                        {
                            "insert": "Test content needs to be 50 characters long, minimum."
                        }
                    ]
                },
                "document_type": "DISCUSSION",
                "full_src": "Test content needs to be 50 characters long, minimum.",
                "renderable_text": "Test content needs to be 50 characters long, minimum.",
            },
        )
        post_id = post_res.data["id"]

        # Create a parent comment with multiple children
        parent_comment = self._create_post_comment(post_id, self.user_1)
        child1 = self._create_post_comment(
            post_id, self.user_2, parent_id=parent_comment.data["id"]
        )
        child2 = self._create_post_comment(
            post_id, self.user_3, parent_id=parent_comment.data["id"]
        )

        # Verify initial discussion count
        post_res = self.client.get(f"/api/researchhubpost/{post_id}/")
        initial_count = post_res.data["discussion_count"]
        self.assertEqual(initial_count, 3)

        # Censor parent comment
        self.client.force_authenticate(self.moderator)
        censor_res = self.client.delete(
            f"/api/researchhubpost/{post_id}/comments/{parent_comment.data['id']}/censor/"
        )

        # Verify discussion count was reduced by 3 (parent + 2 children)
        post_res = self.client.get(f"/api/researchhubpost/{post_id}/")
        self.assertEqual(post_res.data["discussion_count"], 0)

    def test_censor_post_child_with_deleted_parent_preserves_count(self):
        # Create a post
        self.client.force_authenticate(self.user_1)
        post_res = self.client.post(
            "/api/researchhubpost/",
            {
                "title": "Test Post needs to be 20 characters long",
                "content_json": {
                    "ops": [
                        {
                            "insert": "Test content needs to be 50 characters long, minimum."
                        }
                    ]
                },
                "document_type": "DISCUSSION",
                "full_src": "Test content needs to be 50 characters long, minimum.",
                "renderable_text": "Test content needs to be 50 characters long, minimum.",
            },
        )
        post_id = post_res.data["id"]

        # Create parent and child comments
        parent_comment = self._create_post_comment(post_id, self.user_1)
        child_comment = self._create_post_comment(
            post_id, self.user_2, parent_id=parent_comment.data["id"]
        )

        # Delete parent first
        self.client.force_authenticate(self.user_1)
        self.client.delete(
            f"/api/researchhubpost/{post_id}/comments/{parent_comment.data['id']}/"
        )

        # Verify count after parent deletion
        post_res = self.client.get(f"/api/researchhubpost/{post_id}/")
        count_after_parent_delete = post_res.data["discussion_count"]

        # Censor child comment
        self.client.force_authenticate(self.moderator)
        self.client.delete(
            f"/api/researchhubpost/{post_id}/comments/{child_comment.data['id']}/censor/"
        )

        # Verify final count
        post_res = self.client.get(f"/api/researchhubpost/{post_id}/")
        self.assertEqual(
            post_res.data["discussion_count"], count_after_parent_delete - 1
        )

    def test_censor_nested_post_comments(self):
        # Create a post
        self.client.force_authenticate(self.user_1)
        post_res = self.client.post(
            "/api/researchhubpost/",
            {
                "title": "Test Post needs to be 20 characters long",
                "content_json": {
                    "ops": [
                        {
                            "insert": "Test content needs to be 50 characters long, minimum."
                        }
                    ]
                },
                "document_type": "DISCUSSION",
                "full_src": "Test content needs to be 50 characters long, minimum.",
                "renderable_text": "Test content needs to be 50 characters long, minimum.",
            },
        )
        post_id = post_res.data["id"]

        # Create nested comment structure
        parent = self._create_post_comment(post_id, self.user_1)
        child1 = self._create_post_comment(
            post_id, self.user_2, parent_id=parent.data["id"]
        )
        grandchild1 = self._create_post_comment(
            post_id, self.user_3, parent_id=child1.data["id"]
        )
        child2 = self._create_post_comment(
            post_id, self.user_2, parent_id=parent.data["id"]
        )

        # Verify initial count
        post_res = self.client.get(f"/api/researchhubpost/{post_id}/")
        self.assertEqual(post_res.data["discussion_count"], 4)

        # Censor child1 (which should also censor grandchild1)
        self.client.force_authenticate(self.moderator)
        self.client.delete(
            f"/api/researchhubpost/{post_id}/comments/{child1.data['id']}/censor/"
        )

        # Verify count after censoring (should decrease by 2)
        post_res = self.client.get(f"/api/researchhubpost/{post_id}/")
        self.assertEqual(post_res.data["discussion_count"], 2)
