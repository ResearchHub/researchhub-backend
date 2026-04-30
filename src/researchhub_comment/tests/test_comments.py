# flake8: noqa
import time

from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from hub.models import Hub
from notification.models import Notification
from paper.tests.helpers import create_paper
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import Score
from researchhub_comment.models import RhCommentModel
from review.models import Review
from user.models import UserVerification
from user.tests.helpers import create_moderator, create_random_default_user, create_user


def _make_user_verified(user):
    """Create UserVerification (APPROVED) so user.is_verified is True."""
    UserVerification.objects.get_or_create(
        user=user,
        defaults={
            "first_name": user.first_name or "Test",
            "last_name": user.last_name or "User",
            "status": UserVerification.Status.APPROVED,
            "verified_by": UserVerification.Type.MANUAL,
            "external_id": f"test-verified-{user.id}",
        },
    )


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
        self.verified_user = create_random_default_user("verified_user")
        _make_user_verified(self.verified_user)

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

    def _create_review_comment(self, paper_id, created_by, **kwargs):
        return self._create_paper_comment(
            paper_id, created_by, thread_type="REVIEW", comment_type="REVIEW", **kwargs
        )

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

        res = self.client.patch(
            f"/api/paper/{self.paper.id}/comments/{comment.data['id']}/",
            {
                "comment_content_json": {
                    "ops": [{"insert": "this is an updated test comment"}]
                },
            },
        )

        self.assertEqual(res.status_code, 200)

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

    def test_censored_top_level_comments_excluded_from_list(self):
        """
        Test that censored top-level comments are completely excluded
        from the list endpoint.
        """
        parent_comment = self._create_paper_comment(self.paper.id, self.user_1)
        self._create_paper_comment(
            self.paper.id, self.user_2, parent_id=parent_comment.data["id"]
        )
        self._create_paper_comment(
            self.paper.id, self.user_3, parent_id=parent_comment.data["id"]
        )

        # Verify the top-level comment is initially visible in the list
        comments_res = self.client.get(f"/api/paper/{self.paper.id}/comments/")
        self.assertEqual(comments_res.status_code, 200)
        self.assertEqual(comments_res.data["count"], 1)

        # Censor the parent comment
        self.client.force_authenticate(self.moderator)
        censor_res = self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{parent_comment.data['id']}/censor/"
        )
        self.assertEqual(censor_res.status_code, 200)

        # Get comments list again - censored comment should be gone
        comments_res = self.client.get(f"/api/paper/{self.paper.id}/comments/")
        self.assertEqual(comments_res.status_code, 200)
        self.assertEqual(comments_res.data["count"], 0)
        self.assertEqual(len(comments_res.data["results"]), 0)

    def test_censored_nested_comments_excluded_from_children(self):
        """
        Test that censored nested comments are excluded from the parent's
        children in list and detail views.
        """
        parent = self._create_paper_comment(self.paper.id, self.user_1)
        middle = self._create_paper_comment(
            self.paper.id, self.user_2, parent_id=parent.data["id"]
        )
        self._create_paper_comment(
            self.paper.id, self.user_3, parent_id=middle.data["id"]
        )

        # Verify initial state
        comments_res = self.client.get(f"/api/paper/{self.paper.id}/comments/")
        self.assertEqual(comments_res.status_code, 200)
        self.assertEqual(comments_res.data["count"], 1)

        # Censor the middle comment
        self.client.force_authenticate(self.moderator)
        censor_res = self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{middle.data['id']}/censor/"
        )
        self.assertEqual(censor_res.status_code, 200)

        # Parent should still be visible, but the censored middle child excluded
        comments_res = self.client.get(f"/api/paper/{self.paper.id}/comments/")
        self.assertEqual(comments_res.data["count"], 1)
        top_comment = comments_res.data["results"][0]
        self.assertEqual(top_comment["id"], parent.data["id"])

        # The censored middle comment should not appear in parent's children
        child_ids = [c["id"] for c in top_comment["children"]]
        self.assertNotIn(middle.data["id"], child_ids)

        # Directly requesting the censored comment should return 404
        comment_detail_res = self.client.get(
            f"/api/paper/{self.paper.id}/comments/{middle.data['id']}/"
        )
        self.assertEqual(comment_detail_res.status_code, 404)

    def test_nested_censored_comments_excluded_from_hierarchy(self):
        """
        Test that censored comments are excluded from the comment hierarchy.
        """
        parent = self._create_paper_comment(self.paper.id, self.user_1)
        child1 = self._create_paper_comment(
            self.paper.id, self.user_2, parent_id=parent.data["id"]
        )
        self._create_paper_comment(
            self.paper.id, self.user_3, parent_id=child1.data["id"]
        )

        # Censor the middle comment
        self.client.force_authenticate(self.moderator)
        censor_res = self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{child1.data['id']}/censor/"
        )
        self.assertEqual(censor_res.status_code, 200)

        # Get the top-level comment - censored child should be excluded
        comment_detail_res = self.client.get(
            f"/api/paper/{self.paper.id}/comments/{parent.data['id']}/"
        )
        self.assertEqual(comment_detail_res.status_code, 200)
        top_comment = comment_detail_res.data

        # The censored child should not appear in parent's children
        child_ids = [c["id"] for c in top_comment["children"]]
        self.assertNotIn(child1.data["id"], child_ids)

        # Now censor the parent too
        censor_res = self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{parent.data['id']}/censor/"
        )
        self.assertEqual(censor_res.status_code, 200)

        # The list should now be empty since the top-level parent is removed
        comments_res = self.client.get(f"/api/paper/{self.paper.id}/comments/")
        self.assertEqual(comments_res.status_code, 200)
        self.assertEqual(comments_res.data["count"], 0)
        self.assertEqual(len(comments_res.data["results"]), 0)

    def test_censor_parent_cascades_to_descendants(self):
        """Censoring a parent soft-deletes all descendants and updates the
        discussion count to reflect that none of them are visible."""
        parent = self._create_paper_comment(self.paper.id, self.user_1)
        child = self._create_paper_comment(
            self.paper.id, self.user_2, parent_id=parent.data["id"]
        )
        self._create_paper_comment(
            self.paper.id, self.user_3, parent_id=child.data["id"]
        )

        # Arrange -- verify baseline: 1 top-level thread, 3 total comments
        paper_res = self.client.get(f"/api/paper/{self.paper.id}/")
        self.assertEqual(paper_res.data["discussion_count"], 3)

        # Act -- censor only the parent
        self.client.force_authenticate(self.moderator)
        censor_res = self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{parent.data['id']}/censor/"
        )
        self.assertEqual(censor_res.status_code, 200)

        # Assert -- all 3 comments removed, count drops to 0
        paper_res = self.client.get(f"/api/paper/{self.paper.id}/")
        self.assertEqual(paper_res.data["discussion_count"], 0)

        comments_res = self.client.get(f"/api/paper/{self.paper.id}/comments/")
        self.assertEqual(comments_res.data["count"], 0)

    def test_censor_comment_with_bounty_cancels_bounty(self):
        """Censoring a comment cancels its attached bounties."""
        from reputation.models import Bounty

        self._give_rsc(self.user_1, 1_000_000)
        comment = self._create_paper_comment_with_bounty(
            self.paper.id, self.user_1, amount=100
        )
        self.assertEqual(comment.status_code, 201)

        bounty = Bounty.objects.filter(
            item_content_type__model="rhcommentmodel",
            item_object_id=comment.data["id"],
        ).first()
        self.assertEqual(bounty.status, Bounty.OPEN)

        # Act
        self.client.force_authenticate(self.moderator)
        censor_res = self.client.delete(
            f"/api/paper/{self.paper.id}/comments/{comment.data['id']}/censor/"
        )
        self.assertEqual(censor_res.status_code, 200)

        # Assert
        bounty.refresh_from_db()
        self.assertEqual(bounty.status, Bounty.CANCELLED)

    # ------------------------------------------------------------------
    #  DOCUMENT-METADATA METRICS TESTS
    # ------------------------------------------------------------------

    def _get_metadata(self):
        """Helper to fetch the document-metadata payload for ``self.paper``."""
        url = f"/api/researchhub_unified_document/{self.paper.unified_document.id}/get_document_metadata/"
        return self.client.get(url)

    def test_get_document_metadata_review_metrics_update(self):
        """
        Creating an assessed *peer-review* and then deleting it should
        respectively increase and decrease the ``reviews.count`` field
        returned by the ``get_document_metadata`` endpoint.
        """
        from review.models import Review

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

        # Mark the review as assessed so it counts toward review_metrics
        Review.objects.filter(id=review_create_res.data["id"]).update(is_assessed=True)

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

    def test_filter_by_author_update(self):
        author_update_creator = self.paper.created_by
        regular_creator = self.user_2
        self._create_paper_comment(
            self.paper.id,
            created_by=author_update_creator,
            thread_type="AUTHOR_UPDATE",
            comment_type="AUTHOR_UPDATE",
        )
        self._create_paper_comment(self.paper.id, regular_creator)

        author_update_res = self.client.get(
            f"/api/paper/{self.paper.id}/comments/?filtering=AUTHOR_UPDATE&ordering=BEST&ascending=FALSE"
        )
        regular_res = self.client.get(
            f"/api/paper/{self.paper.id}/comments/?ordering=BEST&ascending=FALSE"
        )

        self.assertEqual(author_update_res.status_code, 200)
        self.assertEqual(author_update_res.data["count"], 1)
        self.assertEqual(regular_res.status_code, 200)
        self.assertEqual(regular_res.data["count"], 1)

    def test_best_ordering_verified_user_ranks_above_unverified(self):
        """Verified user's comment should sort above an unverified user's
        comment even when the unverified comment has a higher raw score."""
        # Arrange
        verified = self._create_paper_comment(self.paper.id, self.verified_user)
        unverified = self._create_paper_comment(self.paper.id, self.user_1)
        RhCommentModel.objects.filter(id=unverified.data["id"]).update(score=2)

        # Act
        self.client.force_authenticate(self.user_1)
        res = self.client.get(
            f"/api/paper/{self.paper.id}/comments/?ordering=BEST&ascending=FALSE"
        )

        # Assert
        results = res.data["results"]
        self.assertEqual(results[0]["id"], verified.data["id"])
        self.assertEqual(results[1]["id"], unverified.data["id"])

    def test_best_ordering_review_assessed_outranks_verified(self):
        """For reviews, is_assessed should still outrank weighted_score."""
        # Arrange
        assessed = self._create_review_comment(self.paper.id, self.user_1)
        verified = self._create_review_comment(self.paper.id, self.verified_user)
        Review.objects.create(
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=assessed.data["id"],
            created_by=self.user_1,
            is_assessed=True,
        )

        # Act
        self.client.force_authenticate(self.user_1)
        res = self.client.get(
            f"/api/paper/{self.paper.id}/comments/?filtering=REVIEW&ordering=BEST&ascending=FALSE"
        )

        # Assert
        results = res.data["results"]
        self.assertEqual(results[0]["id"], assessed.data["id"])
        self.assertEqual(results[1]["id"], verified.data["id"])

    def test_best_ordering_review_verified_ranks_higher_within_same_assessed_tier(self):
        """Within the same is_assessed tier, verified user's review should
        sort above unverified user's review."""
        # Arrange
        unverified = self._create_review_comment(self.paper.id, self.user_1)
        verified = self._create_review_comment(self.paper.id, self.verified_user)

        # Act
        self.client.force_authenticate(self.user_1)
        res = self.client.get(
            f"/api/paper/{self.paper.id}/comments/?filtering=REVIEW&ordering=BEST&ascending=FALSE"
        )

        # Assert
        results = res.data["results"]
        self.assertEqual(results[0]["id"], verified.data["id"])
        self.assertEqual(results[1]["id"], unverified.data["id"])
