# flake8: noqa
import time

from rest_framework.test import APITestCase

from hub.models import Hub
from notification.models import Notification
from paper.tests.helpers import create_paper
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import Score
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

    def test_comment_author_can_post_author_update(self):
        # Arrange
        author = self.paper.created_by
        self.client.force_authenticate(author)

        # Act
        res = self.client.post(
            f"/api/paper/{self.paper.id}/comments/create_rh_comment/",
            {
                "comment_content_json": {
                    "ops": [{"insert": "this is an author update"}]
                },
                "thread_type": "AUTHOR_UPDATE",
            },
        )

        # Assert
        self.assertEqual(res.status_code, 200)

    def test_comment_non_author_cant_post_author_update(self):
        # Arrange
        non_author = self.user_1
        self.client.force_authenticate(non_author)

        # Act
        res = self.client.post(
            f"/api/paper/{self.paper.id}/comments/create_rh_comment/",
            {
                "comment_content_json": {
                    "ops": [{"insert": "this is an author update"}]
                },
                "thread_type": "AUTHOR_UPDATE",
            },
        )

        # Assert
        self.assertEqual(res.status_code, 403)

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

        peer_review_res = self.client.get(  # noqa: E501
            f"/api/paper/{self.paper.id}/comments/?filtering=REVIEW&ordering=BEST&ascending=FALSE"
        )
        regular_res = self.client.get(
            f"/api/paper/{self.paper.id}/comments/?ordering=BEST&ascending=FALSE"
        )

        self.assertEqual(peer_review_res.status_code, 200)
        self.assertEqual(peer_review_res.data["count"], 1)
        self.assertEqual(regular_res.status_code, 200)
        self.assertEqual(regular_res.data["count"], 1)

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
        _ = self._create_paper_comment(self.paper.id, regular_creator)
        self._create_paper_comment(self.paper.id, review_creator, thread_type="REVIEW")

        bounty_res = self.client.get(  # noqa: E501
            f"/api/paper/{self.paper.id}/comments/?filtering=BOUNTY&ordering=BEST&ascending=FALSE"
        )
        regular_res = self.client.get(
            f"/api/paper/{self.paper.id}/comments/?ordering=BEST&ascending=FALSE"
        )

        self.assertEqual(bounty_res.status_code, 200)
        self.assertEqual(bounty_res.data["count"], 2)
        self.assertEqual(regular_res.status_code, 200)
        self.assertEqual(regular_res.data["count"], 1)

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

        _ = Score.objects.create(  # noqa: F841
            hub=hub,
            author=user1_with_expertise.author_profile,
            score=100,
        )

        self._give_rsc(self.user_1, 1000000)

        _ = self._create_paper_comment_with_bounty(  # noqa: F841
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

        _ = Score.objects.create(  # noqa: F841
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
        _ = self._create_paper_comment(  # noqa: F841
            self.paper.id, self.user_2, parent_id=parent_comment.data["id"]
        )
        _ = self._create_paper_comment(  # noqa: F841
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

        # Verify censor response returns a censored representation
        self.assertEqual(censor_res.status_code, 200)
        self.assertTrue(censor_res.data["is_removed"])
        self.assertIsNone(censor_res.data["created_by"])
        self.assertEqual(
            censor_res.data["comment_content_json"]["ops"][0]["insert"],
            "[Comment removed]",
        )

        # Child comments should be preserved and accessible
        self.assertTrue("children" in censor_res.data)
        self.assertEqual(len(censor_res.data["children"]), 2)

        # Verify discussion count - with new behavior, count should remain the same
        # as comments are still accessible, just marked as removed
        paper_res = self.client.get(f"/api/paper/{self.paper.id}/")
        self.assertEqual(paper_res.data["discussion_count"], initial_count - 1)

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

        # Directly check if the comment exists
        self.client.force_authenticate(self.moderator)

        # Attempt to censor child2 (middle of chain)
        censor_res = self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{child2.data['id']}/censor/"
        )

        # Verify censor response returns a censored representation
        self.assertEqual(censor_res.status_code, 200)
        self.assertTrue(censor_res.data["is_removed"])
        self.assertIsNone(censor_res.data["created_by"])
        self.assertEqual(
            censor_res.data["comment_content_json"]["ops"][0]["insert"],
            "[Comment removed]",
        )

        # Child comments should be preserved and accessible
        self.assertTrue("children" in censor_res.data)

        # With the new behavior, counts should remain the same since comments are
        # still accessible, just marked as removed
        paper_res = self.client.get(f"/api/paper/{self.paper.id}/")
        self.assertEqual(paper_res.data["discussion_count"], 3)

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

        # Create a parent comment with a child
        parent_comment = self._create_post_comment(post_id, self.user_1)
        self._create_post_comment(
            post_id, self.user_2, parent_id=parent_comment.data["id"]
        )

        # Verify initial discussion count
        post_res = self.client.get(f"/api/researchhubpost/{post_id}/")
        initial_count = post_res.data["discussion_count"]
        # The post has a parent comment and one child comment - total 2 comments
        self.assertEqual(initial_count, 2)

        # Censor parent comment
        self.client.force_authenticate(self.moderator)
        censor_res = self.client.delete(
            f"/api/researchhubpost/{post_id}/comments/{parent_comment.data['id']}/censor/"
        )

        # Verify censor response returns a censored representation
        self.assertEqual(censor_res.status_code, 200)
        self.assertTrue(censor_res.data["is_removed"])
        self.assertIsNone(censor_res.data["created_by"])

        # Child comments should be preserved and accessible
        self.assertTrue("children" in censor_res.data)
        self.assertEqual(censor_res.data["children_count"], 1)

        # With the new behavior, counts should remain the same
        # as comments are still accessible, just marked as removed
        post_res = self.client.get(f"/api/researchhubpost/{post_id}/")
        self.assertEqual(post_res.data["discussion_count"], initial_count - 1)

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
        child1 = self._create_post_comment(
            post_id, self.user_2, parent_id=parent_comment.data["id"]
        )
        # No grandchild comment here; we only need one child to test count logic.

        # Get initial count
        post_res = self.client.get(f"/api/researchhubpost/{post_id}/")
        initial_count = post_res.data["discussion_count"]
        self.assertEqual(initial_count, 2)

        # Delete parent first - attempt regular deletion
        self.client.force_authenticate(self.user_1)
        delete_res = self.client.delete(
            f"/api/researchhubpost/{post_id}/comments/{parent_comment.data['id']}/"
        )
        # API doesn't allow deleting parent comments with child comments
        self.assertEqual(delete_res.status_code, 400)

        # Verify count after parent deletion attempt - should remain unchanged
        post_res = self.client.get(f"/api/researchhubpost/{post_id}/")
        count_after_parent_delete = post_res.data["discussion_count"]
        self.assertEqual(count_after_parent_delete, initial_count)

        # Censor child comment
        self.client.force_authenticate(self.moderator)
        censor_res = self.client.delete(
            f"/api/researchhubpost/{post_id}/comments/{child1.data['id']}/censor/"
        )

        # Verify censor was successful
        self.assertEqual(censor_res.status_code, 200)
        self.assertTrue(censor_res.data["is_removed"])

        # With the new behavior, count remains the same after censoring
        # since censored comments are still accessible, just marked as removed
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
        _child2 = self._create_post_comment(  # noqa: F841
            post_id, self.user_2, parent_id=parent.data["id"]
        )

        # Verify initial count
        post_res = self.client.get(f"/api/researchhubpost/{post_id}/")
        initial_count = post_res.data["discussion_count"]
        self.assertEqual(initial_count, 4)

        # Censor child1 (which should mark it as removed but preserve grandchild1)
        self.client.force_authenticate(self.moderator)
        censor_res = self.client.delete(
            f"/api/researchhubpost/{post_id}/comments/{child1.data['id']}/censor/"
        )

        # Verify censor response returns a censored representation
        self.assertEqual(censor_res.status_code, 200)
        self.assertTrue(censor_res.data["is_removed"])
        self.assertIsNone(censor_res.data["created_by"])

        # Grandchild should be preserved and accessible
        self.assertTrue("children" in censor_res.data)
        self.assertEqual(censor_res.data["children_count"], 1)

        # With the new behavior, counts should remain the same
        # as comments are still accessible, just marked as removed
        post_res = self.client.get(f"/api/researchhubpost/{post_id}/")
        self.assertEqual(post_res.data["discussion_count"], initial_count - 1)

    def test_censored_top_level_comments_appear_in_list(self):
        """
        Test that censored top-level comments still appear in the list endpoint
        but in a sanitized form, with their children intact.
        """
        # Create a parent comment with children
        parent_comment = self._create_paper_comment(self.paper.id, self.user_1)
        child1 = self._create_paper_comment(
            self.paper.id, self.user_2, parent_id=parent_comment.data["id"]
        )
        child2 = self._create_paper_comment(
            self.paper.id, self.user_3, parent_id=parent_comment.data["id"]
        )

        # Verify the top-level comment is initially visible in the list
        comments_res = self.client.get(f"/api/paper/{self.paper.id}/comments/")
        self.assertEqual(comments_res.status_code, 200)
        initial_count = comments_res.data["count"]
        # The list only shows top-level comments
        self.assertEqual(initial_count, 1)

        # Censor the parent comment
        self.client.force_authenticate(self.moderator)
        censor_res = self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{parent_comment.data['id']}/censor/"
        )
        self.assertEqual(censor_res.status_code, 200)

        # Get comments list again
        comments_res = self.client.get(f"/api/paper/{self.paper.id}/comments/")
        self.assertEqual(comments_res.status_code, 200)

        # Should still have the same count of top-level comments
        self.assertEqual(comments_res.data["count"], initial_count)

        # Verify the censored parent comment is still in the results
        censored_parent = comments_res.data["results"][0]
        self.assertEqual(censored_parent["id"], parent_comment.data["id"])

        # Verify it's properly sanitized
        self.assertTrue(censored_parent["is_removed"])
        self.assertIsNone(censored_parent["created_by"])
        self.assertEqual(
            censored_parent["comment_content_json"]["ops"][0]["insert"],
            "[Comment removed]",
        )

        # Verify children are still associated
        self.assertEqual(censored_parent["children_count"], 2)
        child_ids = {child1.data["id"], child2.data["id"]}
        result_child_ids = {child["id"] for child in censored_parent["children"]}
        self.assertEqual(child_ids, result_child_ids)

        # Verify child comments have proper content
        for child in censored_parent["children"]:
            self.assertFalse(child.get("is_removed", False))
            self.assertIsNotNone(child["created_by"])
            self.assertNotEqual(
                child["comment_content_json"]["ops"][0]["insert"], "[Comment removed]"
            )

    def test_censored_nested_comments_appear_in_list(self):
        """
        Test that censored nested comments still appear in the list endpoint
        but in a sanitized form, with their children intact.
        """
        # Create a nested structure of comments
        parent = self._create_paper_comment(self.paper.id, self.user_1)
        middle = self._create_paper_comment(
            self.paper.id, self.user_2, parent_id=parent.data["id"]
        )
        child = self._create_paper_comment(
            self.paper.id, self.user_3, parent_id=middle.data["id"]
        )

        # Verify initial state
        comments_res = self.client.get(f"/api/paper/{self.paper.id}/comments/")
        self.assertEqual(comments_res.status_code, 200)

        # Should have 1 top-level comment (list endpoint only shows top-level)
        self.assertEqual(comments_res.data["count"], 1)

        # Censor the middle comment
        self.client.force_authenticate(self.moderator)
        censor_res = self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{middle.data['id']}/censor/"
        )
        self.assertEqual(censor_res.status_code, 200)

        # Get the top-level comment from the list
        comments_res = self.client.get(f"/api/paper/{self.paper.id}/comments/")
        top_comment = comments_res.data["results"][0]

        # Get the individual comment details to check children
        comment_detail_res = self.client.get(
            f"/api/paper/{self.paper.id}/comments/{middle.data['id']}/"
        )
        self.assertEqual(comment_detail_res.status_code, 200)
        middle_comment = comment_detail_res.data

        # Verify middle comment is properly sanitized
        self.assertEqual(middle_comment["id"], middle.data["id"])
        self.assertTrue(middle_comment["is_removed"])
        self.assertIsNone(middle_comment["created_by"])
        self.assertEqual(
            middle_comment["comment_content_json"]["ops"][0]["insert"],
            "[Comment removed]",
        )

        # Verify middle comment's child is still visible
        self.assertEqual(middle_comment["children_count"], 1)
        self.assertEqual(len(middle_comment["children"]), 1)
        child_comment = middle_comment["children"][0]

        # Child should not be sanitized
        self.assertEqual(child_comment["id"], child.data["id"])
        self.assertFalse(child_comment.get("is_removed", False))
        self.assertIsNotNone(child_comment["created_by"])
        self.assertNotEqual(
            child_comment["comment_content_json"]["ops"][0]["insert"],
            "[Comment removed]",
        )

    def test_censored_comments_visibility(self):
        """
        Test to verify that censored comments are returned by the list endpoint
        but with sanitized content.
        """
        # Create a top-level comment
        parent_comment = self._create_paper_comment(self.paper.id, self.user_1)

        # Verify the comment is initially visible
        comments_res = self.client.get(f"/api/paper/{self.paper.id}/comments/")
        self.assertEqual(comments_res.status_code, 200)
        initial_count = comments_res.data["count"]
        self.assertEqual(initial_count, 1)

        # Censor the comment
        self.client.force_authenticate(self.moderator)
        censor_res = self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{parent_comment.data['id']}/censor/"
        )
        self.assertEqual(censor_res.status_code, 200)

        # Check if comment is still in list - should be included with our updated queryset
        comments_res = self.client.get(f"/api/paper/{self.paper.id}/comments/")
        self.assertEqual(comments_res.status_code, 200)

        # Count should remain the same since censored comments are now included
        self.assertEqual(comments_res.data["count"], initial_count)

        # The censored comment should be in the results
        censored_comment = comments_res.data["results"][0]
        self.assertEqual(censored_comment["id"], parent_comment.data["id"])

        # Verify it's properly sanitized
        self.assertTrue(censored_comment["is_removed"])
        self.assertIsNone(censored_comment["created_by"])
        self.assertEqual(
            censored_comment["comment_content_json"]["ops"][0]["insert"],
            "[Comment removed]",
        )

    def test_nested_censored_comments_visibility(self):
        """
        Test that censored comments at different levels in the hierarchy
        are properly sanitized but remain visible in the comment tree.
        """
        # Create a nested comment structure
        parent = self._create_paper_comment(self.paper.id, self.user_1)
        child1 = self._create_paper_comment(
            self.paper.id, self.user_2, parent_id=parent.data["id"]
        )
        child2 = self._create_paper_comment(
            self.paper.id, self.user_3, parent_id=child1.data["id"]
        )

        # Censor the middle comment
        self.client.force_authenticate(self.moderator)
        censor_res = self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{child1.data['id']}/censor/"
        )
        self.assertEqual(censor_res.status_code, 200)

        # Get the top-level comment directly, which should include its censored child and grandchild
        comment_detail_res = self.client.get(
            f"/api/paper/{self.paper.id}/comments/{parent.data['id']}/"
        )
        self.assertEqual(comment_detail_res.status_code, 200)
        top_comment = comment_detail_res.data

        # Check the comment structure directly - parent should have a censored child
        self.assertEqual(
            len(top_comment["children"]), 1, "The parent should have exactly one child"
        )

        # The child should be censored
        censored_child = top_comment["children"][0]
        self.assertEqual(censored_child["id"], child1.data["id"])
        self.assertTrue(censored_child["is_removed"])
        self.assertIsNone(censored_child["created_by"])
        self.assertEqual(
            censored_child["comment_content_json"]["ops"][0]["insert"],
            "[Comment removed]",
        )

        # The censored comment should still have its child visible
        self.assertEqual(len(censored_child["children"]), 1)
        grandchild = censored_child["children"][0]
        self.assertEqual(grandchild["id"], child2.data["id"])
        self.assertFalse(grandchild.get("is_removed", False))

        # Now censor the parent and verify the entire hierarchy is still visible
        censor_res = self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{parent.data['id']}/censor/"
        )
        self.assertEqual(censor_res.status_code, 200)

        # Get the list - parent should be censored but still present
        comments_res = self.client.get(f"/api/paper/{self.paper.id}/comments/")
        self.assertEqual(comments_res.status_code, 200)
        self.assertEqual(comments_res.data["count"], 1)

        # Parent should be censored
        censored_parent = comments_res.data["results"][0]
        self.assertEqual(censored_parent["id"], parent.data["id"])
        self.assertTrue(censored_parent["is_removed"])

        # The hierarchy should be preserved
        self.assertEqual(len(censored_parent["children"]), 1)
        middle_comment = censored_parent["children"][0]
        self.assertEqual(middle_comment["id"], child1.data["id"])

        # Both parent and middle are censored, grandchild is still intact
        self.assertTrue(middle_comment["is_removed"])
        self.assertEqual(len(middle_comment["children"]), 1)
        grandchild = middle_comment["children"][0]
        self.assertEqual(grandchild["id"], child2.data["id"])
        self.assertFalse(grandchild.get("is_removed", False))

    # ------------------------------------------------------------------
    #  DOCUMENT-METADATA METRICS TESTS
    # ------------------------------------------------------------------

    def _get_metadata(self):
        """Helper to fetch the document-metadata payload for ``self.paper``."""
        url = f"/api/researchhub_unified_document/{self.paper.unified_document.id}/get_document_metadata/"
        return self.client.get(url)

    def test_get_document_metadata_review_metrics_update(self):
        """
        Creating a *peer-review* and then deleting it should respectively
        increase and decrease the ``reviews.count`` field returned by the
        ``get_document_metadata`` endpoint.
        """

        # Authenticate as user_1 who will author the review comment & review
        self.client.force_authenticate(self.user_1)

        # 1) Baseline – there should be *no* reviews initially
        baseline_meta = self._get_metadata()
        self.assertEqual(baseline_meta.status_code, 200)
        baseline_review_count = baseline_meta.data["reviews"]["count"]
        self.assertEqual(baseline_review_count, 0)

        # 2) Create a *peer-review* RhComment **and** a corresponding Review
        # ----------------------------------------------------------------
        #   a) Create the peer-review comment itself
        comment_res = self._create_paper_comment(
            self.paper.id,
            self.user_1,
            thread_type="REVIEW",
            comment_type="REVIEW",
        )
        self.assertEqual(comment_res.status_code, 200)
        comment_id = comment_res.data["id"]

        #   b) Create a Review object that references this comment
        review_create_res = self.client.post(
            f"/api/researchhub_unified_document/{self.paper.unified_document.id}/review/",
            {
                "score": 8,
                "content_type": "rhcommentmodel",
                "object_id": comment_id,
            },
        )
        self.assertIn(review_create_res.status_code, (200, 201))

        # 3) Metadata should now report *one* review
        after_create_meta = self._get_metadata()
        self.assertEqual(after_create_meta.status_code, 200)
        self.assertEqual(
            after_create_meta.data["reviews"]["count"], baseline_review_count + 1
        )

        # 4) Delete the review (soft-delete)
        review_id = review_create_res.data["id"]
        review_delete_res = self.client.delete(
            f"/api/researchhub_unified_document/{self.paper.unified_document.id}/review/{review_id}/"
        )
        self.assertIn(review_delete_res.status_code, (200, 204))

        # 5) Metadata should revert back to the baseline count
        after_delete_meta = self._get_metadata()
        self.assertEqual(
            after_delete_meta.data["reviews"]["count"], baseline_review_count
        )

    def test_get_document_metadata_discussion_count_update(self):
        """
        Creating a *generic* comment should increase the `discussion_count`
        inside the document-metadata payload. Deleting that comment should
        bring the count back down.
        """

        self.client.force_authenticate(self.user_1)

        # Helper to pull discussion_count from metadata
        def _discussion_count():
            meta = self._get_metadata()
            self.assertEqual(meta.status_code, 200)
            documents_field = meta.data["documents"]
            # For papers, `documents` is a dict; for posts it may be a list.
            if isinstance(documents_field, list):
                doc_payload = documents_field[0]
            else:
                doc_payload = documents_field
            return doc_payload["discussion_aggregates"]["discussion_count"]

        baseline_discussion_ct = _discussion_count()

        # Create a *generic* top-level comment (counts toward discussion_count)
        comment_res = self._create_paper_comment(self.paper.id, self.user_1)
        self.assertEqual(comment_res.status_code, 200)
        comment_id = comment_res.data["id"]

        # Confirm increment
        self.assertEqual(_discussion_count(), baseline_discussion_ct + 1)

        # Censor the comment (soft delete)
        censor_res = self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{comment_id}/censor/"
        )
        # Using censor instead of destroy; expect success
        self.assertEqual(censor_res.status_code, 200)

        # Count should revert to baseline
        self.assertEqual(_discussion_count(), baseline_discussion_ct)
