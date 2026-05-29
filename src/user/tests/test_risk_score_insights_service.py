from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from purchase.related_models.grant_model import Grant
from purchase.related_models.purchase_model import Purchase
from reputation.related_models.bounty import Bounty, BountySolution
from reputation.related_models.escrow import Escrow
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.helpers import create_post
from review.models.review_model import Review
from user.related_models.risk_score_model import RiskScoreEvent
from user.services.risk_score_insights_service import (
    MIXED,
    NEGATIVE,
    POSITIVE,
    build_event_details,
    build_insights,
)
from user.services.risk_score_service import RiskScoreService
from user.tests.helpers import create_user

EventType = RiskScoreEvent.EventType


def _create_comment(post, author, body="hello world"):
    thread = RhCommentThreadModel.objects.create(
        content_type=ContentType.objects.get_for_model(post),
        object_id=post.id,
        created_by=author,
    )
    return RhCommentModel.objects.create(
        thread=thread,
        created_by=author,
        comment_content_json={"ops": [{"insert": body}]},
    )


def _record(user, event_type, *, source=None, delta=None):
    return RiskScoreService().record_event(user, event_type, source=source, delta=delta)


def _record_many(user, event_type, count, *, delta=None):
    for _ in range(count):
        RiskScoreEvent.objects.create(
            user=user,
            event_type=event_type,
            delta=delta if delta is not None else RiskScoreEvent.DELTAS[event_type],
        )


class BuildEventDetailsTests(APITestCase):
    def setUp(self):
        self.user = create_user(email="author@test.com")
        self.post = create_post(created_by=self.user, title="Quantum Computing")

    def test_one_time_event_returns_none(self):
        # Arrange
        _record(self.user, EventType.GOOGLE_SIGNUP)
        event = RiskScoreEvent.objects.get(user=self.user)

        # Act
        details = build_event_details([event])

        # Assert
        self.assertIsNone(details[event.id])

    def test_grant_detail_prefers_underlying_post_title(self):
        # Arrange
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=1000,
            description="Funding for new research projects in computing.",
            short_title="Compute Grant",
        )
        event = _record(self.user, EventType.WORK_APPROVED, source=grant)

        # Act
        detail = build_event_details([event])[event.id]

        # Assert
        self.assertEqual(detail["title"], "Quantum Computing")
        self.assertIn("Funding for new research", detail["snippet"])
        self.assertIsNotNone(detail["url"])
        self.assertEqual(detail["document_type"], "DISCUSSION")
        self.assertIsNone(detail["comment_type"])

    def test_grant_detail_falls_back_to_short_title(self):
        # Arrange
        unified_doc = create_post(created_by=self.user, title="").unified_document
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=unified_doc,
            amount=500,
            description="Backup grant.",
            short_title="Backup",
        )
        event = _record(self.user, EventType.WORK_APPROVED, source=grant)

        # Act
        detail = build_event_details([event])[event.id]

        # Assert
        self.assertEqual(detail["title"], "Backup")

    def test_post_detail_includes_title_and_document_type(self):
        # Arrange
        event = _record(self.user, EventType.WORK_APPROVED, source=self.post)

        # Act
        detail = build_event_details([event])[event.id]

        # Assert
        self.assertEqual(detail["title"], "Quantum Computing")
        self.assertEqual(detail["snippet"], "some text")
        self.assertEqual(detail["document_type"], "DISCUSSION")
        self.assertIsNone(detail["comment_type"])

    def test_comment_detail_includes_anchor_and_types(self):
        # Arrange
        comment = _create_comment(self.post, self.user, "this is the censored comment")
        comment.comment_type = "PEER_REVIEW"
        comment.save(update_fields=["comment_type"])
        event = _record(self.user, EventType.CONTENT_CENSORED, source=comment)

        # Act
        detail = build_event_details([event])[event.id]

        # Assert
        self.assertEqual(detail["snippet"], "this is the censored comment")
        self.assertTrue(detail["url"].endswith(f"#comment-{comment.id}"))
        self.assertEqual(detail["comment_type"], "PEER_REVIEW")
        self.assertEqual(detail["document_type"], "DISCUSSION")

    def test_unified_document_detail_includes_document_type(self):
        # Arrange
        event = _record(
            self.user,
            EventType.CONTENT_CENSORED,
            source=self.post.unified_document,
        )

        # Act
        detail = build_event_details([event])[event.id]

        # Assert
        self.assertEqual(detail["title"], "Quantum Computing")
        self.assertEqual(detail["document_type"], "DISCUSSION")
        self.assertIsNone(detail["comment_type"])

    def test_bounty_solution_resolves_comment_item(self):
        # Arrange
        comment = _create_comment(self.post, self.user, "bounty answer")
        comment_ct = ContentType.objects.get_for_model(comment)
        post_ct = ContentType.objects.get_for_model(self.post)
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            content_type=post_ct,
            object_id=self.post.id,
        )
        bounty = Bounty.objects.create(
            created_by=self.user,
            amount=100,
            item_content_type=comment_ct,
            item_object_id=comment.id,
            unified_document=self.post.unified_document,
            escrow=escrow,
        )
        with self.captureOnCommitCallbacks(execute=True):
            BountySolution.objects.create(
                bounty=bounty,
                created_by=self.user,
                content_type=comment_ct,
                object_id=comment.id,
                status=BountySolution.Status.AWARDED,
            )
        event = RiskScoreEvent.objects.get(
            user=self.user, event_type=EventType.BOUNTY_AWARDED
        )

        # Act
        detail = build_event_details([event])[event.id]

        # Assert
        self.assertEqual(detail["title"], "Quantum Computing")
        self.assertEqual(detail["snippet"], "bounty answer")
        self.assertTrue(detail["url"].endswith(f"#comment-{comment.id}"))
        self.assertEqual(detail["comment_type"], "GENERIC_COMMENT")
        self.assertEqual(detail["document_type"], "DISCUSSION")

    def test_purchase_detail_resolves_comment(self):
        # Arrange
        comment = _create_comment(self.post, self.user, "tipped comment")
        purchase = Purchase.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(comment),
            object_id=comment.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
            amount="100",
        )
        event = _record(self.user, EventType.PEER_REVIEW_TIPPED, source=purchase)

        # Act
        detail = build_event_details([event])[event.id]

        # Assert
        self.assertEqual(detail["snippet"], "tipped comment")
        self.assertTrue(detail["url"].endswith(f"#comment-{comment.id}"))
        self.assertEqual(detail["comment_type"], "GENERIC_COMMENT")
        self.assertEqual(detail["document_type"], "DISCUSSION")

    def test_review_resolves_comment_item(self):
        # Arrange
        comment = _create_comment(self.post, self.user, "reviewed comment")
        review = Review.objects.create(
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(comment),
            object_id=comment.id,
            unified_document=self.post.unified_document,
            is_assessed=True,
        )
        event = _record(self.user, EventType.PEER_REVIEW_ASSESSED, source=review)

        # Act
        detail = build_event_details([event])[event.id]

        # Assert
        self.assertEqual(detail["title"], "Quantum Computing")
        self.assertEqual(detail["snippet"], "reviewed comment")
        self.assertTrue(detail["url"].endswith(f"#comment-{comment.id}"))
        self.assertEqual(detail["comment_type"], "GENERIC_COMMENT")
        self.assertEqual(detail["document_type"], "DISCUSSION")

    def test_returns_none_for_missing_source(self):
        # Arrange
        comment = _create_comment(self.post, self.user)
        event = _record(self.user, EventType.CONTENT_CENSORED, source=comment)
        comment.delete(soft=False)

        # Act
        details = build_event_details([event])

        # Assert
        self.assertIsNone(details[event.id])

    def test_resolves_soft_deleted_source(self):
        # Arrange
        comment = _create_comment(self.post, self.user, "censored later")
        event = _record(self.user, EventType.CONTENT_CENSORED, source=comment)
        comment.is_removed = True
        comment.save(update_fields=["is_removed"])

        # Act
        detail = build_event_details([event])[event.id]

        # Assert
        self.assertEqual(detail["snippet"], "censored later")

    def test_batches_source_fetch_by_content_type(self):
        # Arrange
        comment_a = _create_comment(self.post, self.user, "first")
        comment_b = _create_comment(self.post, self.user, "second")
        event_a = _record(self.user, EventType.CONTENT_CENSORED, source=comment_a)
        event_b = _record(self.user, EventType.CONTENT_CENSORED, source=comment_b)

        # Act
        with CaptureQueriesContext(connection) as ctx:
            build_event_details([event_a, event_b])

        # Assert
        comment_fetches = [
            q
            for q in ctx.captured_queries
            if 'FROM "researchhub_comment_rhcommentmodel"' in q["sql"]
        ]
        self.assertEqual(len(comment_fetches), 1)


class BuildInsightsTests(APITestCase):
    def setUp(self):
        self.user = create_user(email="insights@test.com")

    def test_returns_empty_when_no_events(self):
        # Act
        insights = build_insights(self.user)

        # Assert
        self.assertEqual(insights, [])

    def test_negative_deltas_are_positive_sentiment(self):
        # Arrange
        _record_many(self.user, EventType.GOOGLE_SIGNUP, 1)

        # Act
        insights = build_insights(self.user)

        # Assert
        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0]["sentiment"], POSITIVE)
        self.assertEqual(insights[0]["count"], 1)
        self.assertEqual(
            insights[0]["total_delta"],
            RiskScoreEvent.DELTAS[EventType.GOOGLE_SIGNUP],
        )

    def test_positive_deltas_are_negative_sentiment(self):
        # Arrange
        _record_many(self.user, EventType.CONTENT_CENSORED, 3)

        # Act
        insights = build_insights(self.user)

        # Assert
        self.assertEqual(insights[0]["sentiment"], NEGATIVE)
        self.assertEqual(insights[0]["count"], 3)
        self.assertEqual(
            insights[0]["total_delta"],
            RiskScoreEvent.DELTAS[EventType.CONTENT_CENSORED] * 3,
        )

    def test_mixed_signs_within_event_type_are_mixed(self):
        # Arrange
        _record_many(self.user, EventType.WORK_APPROVED, 1, delta=-50)
        _record_many(self.user, EventType.WORK_APPROVED, 1, delta=10)

        # Act
        insights = build_insights(self.user)

        # Assert
        self.assertEqual(insights[0]["sentiment"], MIXED)

    def test_unrelated_event_types_stay_separate(self):
        # Arrange
        _record_many(self.user, EventType.CONTENT_CENSORED, 2)
        _record_many(self.user, EventType.GOOGLE_SIGNUP, 1)

        # Act
        insights = build_insights(self.user)

        # Assert
        by_type = {row["event_type"]: row for row in insights}
        self.assertEqual(by_type[EventType.CONTENT_CENSORED]["count"], 2)
        self.assertEqual(by_type[EventType.GOOGLE_SIGNUP]["count"], 1)

    def test_works_moderated_consolidates_approved_and_declined(self):
        # Arrange
        _record_many(self.user, EventType.WORK_APPROVED, 18)
        _record_many(self.user, EventType.WORK_DECLINED, 13)

        # Act
        insights = build_insights(self.user)

        # Assert
        by_type = {row["event_type"]: row for row in insights}
        works = by_type["WORKS_MODERATED"]
        self.assertEqual(works["count"], 31)
        self.assertEqual(
            works["total_delta"],
            RiskScoreEvent.DELTAS[EventType.WORK_APPROVED] * 18
            + RiskScoreEvent.DELTAS[EventType.WORK_DECLINED] * 13,
        )
        self.assertEqual(works["sentiment"], MIXED)
        self.assertNotIn(EventType.WORK_APPROVED, by_type)
        self.assertNotIn(EventType.WORK_DECLINED, by_type)

    def test_works_moderated_is_positive_when_only_approvals(self):
        # Arrange
        _record_many(self.user, EventType.WORK_APPROVED, 2)

        # Act
        insights = build_insights(self.user)

        # Assert
        self.assertEqual(insights[0]["event_type"], "WORKS_MODERATED")
        self.assertEqual(insights[0]["sentiment"], POSITIVE)

    def test_persona_verified_consolidates_country_variants(self):
        # Arrange
        _record_many(self.user, EventType.PERSONA_VERIFIED_WHITELISTED, 1)
        _record_many(self.user, EventType.PERSONA_VERIFIED_NON_WHITELISTED, 1)

        # Act
        insights = build_insights(self.user)

        # Assert
        by_type = {row["event_type"]: row for row in insights}
        self.assertIn("PERSONA_VERIFIED", by_type)
        self.assertEqual(by_type["PERSONA_VERIFIED"]["count"], 2)

    def test_runs_in_a_single_query(self):
        # Arrange
        _record_many(self.user, EventType.WORK_APPROVED, 2)
        _record_many(self.user, EventType.CONTENT_CENSORED, 3)

        # Act & Assert
        with self.assertNumQueries(1):
            build_insights(self.user)


class RiskScoreEventsApiTests(APITestCase):
    def setUp(self):
        self.moderator = create_user(email="mod@test.com", moderator=True)
        self.target = create_user(email="target@test.com")
        self.post = create_post(created_by=self.target, title="Subject paper")
        self.client.force_authenticate(user=self.moderator)

    def test_response_includes_source_detail_and_insights(self):
        # Arrange
        comment = _create_comment(self.post, self.target, "spammy comment")
        _record(self.target, EventType.CONTENT_CENSORED, source=comment)
        _record(self.target, EventType.GOOGLE_SIGNUP)
        url = f"/api/moderator/{self.target.id}/risk_score_events/"

        # Act
        response = self.client.get(url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.data)
        self.assertIn("insights", response.data)
        sentiments = {
            row["event_type"]: row["sentiment"] for row in response.data["insights"]
        }
        self.assertEqual(sentiments[EventType.CONTENT_CENSORED], NEGATIVE)
        self.assertEqual(sentiments[EventType.GOOGLE_SIGNUP], POSITIVE)
        details_by_type = {
            row["event_type"]: row["source_detail"] for row in response.data["results"]
        }
        self.assertIsNone(details_by_type[EventType.GOOGLE_SIGNUP])
        self.assertEqual(
            details_by_type[EventType.CONTENT_CENSORED]["snippet"],
            "spammy comment",
        )
