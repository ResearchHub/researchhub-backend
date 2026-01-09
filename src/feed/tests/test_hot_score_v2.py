"""
Integration tests for hot score v2 (JSON-based) algorithm.

These tests validate that the hot score calculation uses FeedEntry.content
and FeedEntry.metrics JSON fields instead of querying related models.
"""

from datetime import datetime, timedelta, timezone

from django.contrib.contenttypes.models import ContentType

from feed.models import FeedEntry, HotScoreV2Breakdown
from researchhub_document.helpers import create_post
from user.tests.helpers import create_random_default_user
from utils.test_helpers import AWSMockTestCase


class TestHotScoreV2(AWSMockTestCase):
    """Integration tests for hot score v2 (JSON-based) algorithm."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.user = create_random_default_user("hotscore_v2_test")
        self.now = datetime.now(timezone.utc)

    def test_basic_hot_score_calculation(self):
        """Test basic hot score calculation with simple metrics."""
        post = create_post(created_by=self.user)

        content = {"id": post.id, "title": "Test Post", "bounties": [], "purchases": []}

        metrics = {"votes": 10, "replies": 0, "review_metrics": {"count": 0}}

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        score = feed_entry.calculate_hot_score_v2()

        # Verify score is calculated and is an integer
        self.assertGreater(score, 0)
        self.assertIsInstance(score, int)

        # Verify breakdown was created in separate table
        self.assertTrue(hasattr(feed_entry, "hot_score_breakdown_v2"))
        self.assertIsNotNone(feed_entry.hot_score_breakdown_v2)
        self.assertIsInstance(feed_entry.hot_score_breakdown_v2, HotScoreV2Breakdown)
        self.assertIn("calculation", feed_entry.hot_score_breakdown_v2.breakdown_data)

    def test_json_fields_used_not_models(self):
        """Test that JSON metrics are used, not model attributes."""
        post = create_post(created_by=self.user)
        post.score = 0  # Model has no votes
        post.save()

        content = {"id": post.id, "title": "Test Post", "bounties": [], "purchases": []}

        # JSON says 100 votes, but model score is 0
        metrics = {"votes": 100, "replies": 0, "review_metrics": {"count": 0}}

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        score = feed_entry.calculate_hot_score_v2()

        # Score should be based on JSON metrics (100), not model (0)
        self.assertGreater(score, 100)

    def test_lazy_loading_no_unified_document_access_without_comments(self):
        """Test that unified_document isn't accessed when there are no comments."""
        post = create_post(created_by=self.user)

        content = {"id": post.id, "title": "Test Post", "bounties": [], "purchases": []}

        # No comments
        metrics = {"votes": 10, "replies": 0, "review_metrics": {"count": 0}}

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        # Temporarily set unified_document to None
        feed_entry.unified_document = None

        # Should not raise an error (unified_document shouldn't be accessed)
        score = feed_entry.calculate_hot_score_v2()

        self.assertGreater(score, 0)

    def test_recency_signal_new_vs_old_posts(self):
        """Test that recency signal gives new posts higher scores than old posts.

        Recency signal: 24 / (age_hours + 24)
        - At 0h: 1.0 → component ~21
        - At 72h: 0.25 → component ~7
        """
        # Create new post
        new_post = create_post(created_by=self.user)

        # Create old post (72 hours ago)
        old_post = create_post(created_by=self.user)
        old_created = self.now - timedelta(hours=72)

        # Identical content and metrics
        content = {"id": 1, "title": "Test", "bounties": [], "purchases": []}
        metrics = {"votes": 5, "replies": 0, "review_metrics": {"count": 0}}

        new_entry = FeedEntry.objects.create(
            item=new_post,
            unified_document=new_post.unified_document,
            content_type=ContentType.objects.get_for_model(new_post),
            object_id=new_post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )
        new_entry.created_date = self.now
        new_entry.save()

        old_entry = FeedEntry.objects.create(
            item=old_post,
            unified_document=old_post.unified_document,
            content_type=ContentType.objects.get_for_model(old_post),
            object_id=old_post.id,
            action=FeedEntry.PUBLISH,
            action_date=old_created,
            content={**content, "created_date": old_created.isoformat()},
            metrics=metrics,
        )
        old_entry.created_date = old_created
        old_entry.save()

        new_score = new_entry.calculate_hot_score_v2()
        old_score = old_entry.calculate_hot_score_v2()

        # New post should have higher score due to recency signal
        # Recency contributes ~21 pts at 0h vs ~7 pts at 72h
        # Combined with time decay, new content should clearly rank higher
        self.assertGreater(new_score, old_score)

    def test_bounty_from_json_content(self):
        """Test that bounties in content JSON contribute to hot score."""
        post = create_post(created_by=self.user)

        content = {
            "id": post.id,
            "title": "Test Post",
            "bounties": [
                {
                    "id": 1,
                    "amount": "500.0000000000",
                    "status": "OPEN",
                    "expiration_date": (self.now + timedelta(days=10)).isoformat(),
                }
            ],
            "purchases": [],
        }

        metrics = {"votes": 5, "replies": 0, "review_metrics": {"count": 0}}

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        score_with_bounty = feed_entry.calculate_hot_score_v2()

        # Create entry without bounty for comparison
        content_no_bounty = {
            "id": post.id,
            "title": "Test Post",
            "bounties": [],
            "purchases": [],
        }

        feed_entry.content = content_no_bounty
        feed_entry.save()

        score_without_bounty = feed_entry.calculate_hot_score_v2()

        # Bounty should increase score
        self.assertGreater(score_with_bounty, score_without_bounty)

    def test_bounty_urgency_multiplier(self):
        """Test that urgent bounties get 1.5x multiplier."""
        post = create_post(created_by=self.user)

        # Make feed entry old enough so only expiration matters
        # (not "newly created" urgency)
        old_date = self.now - timedelta(days=10)

        # Urgent bounty (expiring in 24 hours)
        urgent_content = {
            "id": post.id,
            "title": "Test Post",
            "bounties": [
                {
                    "id": 1,
                    "amount": "500.0000000000",
                    "status": "OPEN",
                    "expiration_date": (self.now + timedelta(hours=24)).isoformat(),
                }
            ],
            "purchases": [],
        }

        # Non-urgent bounty (expiring in 7 days)
        non_urgent_content = {
            "id": post.id,
            "title": "Test Post",
            "bounties": [
                {
                    "id": 2,
                    "amount": "500.0000000000",
                    "status": "OPEN",
                    "expiration_date": (self.now + timedelta(days=7)).isoformat(),
                }
            ],
            "purchases": [],
        }

        metrics = {"votes": 5, "replies": 0, "review_metrics": {"count": 0}}

        urgent_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=old_date,
            content=urgent_content,
            metrics=metrics,
        )
        # Set created_date to old date to avoid "newly created" urgency
        urgent_entry.created_date = old_date
        urgent_entry.save()

        urgent_score = urgent_entry.calculate_hot_score_v2()

        # Update same entry with non-urgent bounty
        urgent_entry.content = non_urgent_content
        urgent_entry.save()

        non_urgent_score = urgent_entry.calculate_hot_score_v2()

        # Urgent bounty should have higher score (1.5x multiplier)
        self.assertGreater(urgent_score, non_urgent_score)

    def test_tips_from_purchases_json(self):
        """Test that purchases in content JSON contribute to hot score."""
        post = create_post(created_by=self.user)

        content = {
            "id": post.id,
            "title": "Test Post",
            "bounties": [],
            "purchases": [{"id": 1, "amount": "100"}, {"id": 2, "amount": "50"}],
        }

        metrics = {"votes": 5, "replies": 0, "review_metrics": {"count": 0}}

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        score_with_tips = feed_entry.calculate_hot_score_v2()

        # Remove purchases
        feed_entry.content = {
            "id": post.id,
            "title": "Test Post",
            "bounties": [],
            "purchases": [],
        }
        feed_entry.save()

        score_without_tips = feed_entry.calculate_hot_score_v2()

        # Tips should increase score
        self.assertGreater(score_with_tips, score_without_tips)

    def test_grant_deadline_urgency(self):
        """Test that grants with approaching deadlines appear newer."""
        post = create_post(created_by=self.user)

        # Grant with deadline in 3 days (within 7-day urgency window)
        urgent_grant_content = {
            "id": post.id,
            "type": "GRANT",
            "title": "Urgent Grant",
            "grant": {"end_date": (self.now + timedelta(days=3)).isoformat()},
            "bounties": [],
            "purchases": [],
            "created_date": (self.now - timedelta(days=30)).isoformat(),
        }

        # Grant with deadline in 30 days (no urgency)
        normal_grant_content = {
            "id": post.id,
            "type": "GRANT",
            "title": "Normal Grant",
            "grant": {"end_date": (self.now + timedelta(days=30)).isoformat()},
            "bounties": [],
            "purchases": [],
            "created_date": (self.now - timedelta(days=30)).isoformat(),
        }

        metrics = {"votes": 5, "replies": 0, "review_metrics": {"count": 0}}

        # Create entry for urgent grant
        urgent_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now - timedelta(days=30),
            content=urgent_grant_content,
            metrics=metrics,
        )
        urgent_entry.created_date = self.now - timedelta(days=30)
        urgent_entry.save()

        urgent_score = urgent_entry.calculate_hot_score_v2()

        # Update to normal grant
        urgent_entry.content = normal_grant_content
        urgent_entry.save()

        normal_score = urgent_entry.calculate_hot_score_v2()

        # Urgent grant should have higher score (appears newer)
        self.assertGreater(urgent_score, normal_score)

    def test_preregistration_fundraise_amount(self):
        """Test that fundraise amounts are treated as tips."""
        post = create_post(created_by=self.user)

        content = {
            "id": post.id,
            "type": "PREREGISTRATION",
            "title": "Test Preregistration",
            "fundraise": {"amount_raised": {"rsc": 500, "usd": 200}},
            "bounties": [],
            "purchases": [],
        }

        metrics = {"votes": 5, "replies": 0, "review_metrics": {"count": 0}}

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        score_with_fundraise = feed_entry.calculate_hot_score_v2()

        # Remove fundraise
        feed_entry.content = {
            "id": post.id,
            "type": "PREREGISTRATION",
            "title": "Test Preregistration",
            "fundraise": None,
            "bounties": [],
            "purchases": [],
        }
        feed_entry.save()

        score_without_fundraise = feed_entry.calculate_hot_score_v2()

        # Fundraise should increase score (treated as tips)
        self.assertGreater(score_with_fundraise, score_without_fundraise)

    def test_handles_empty_json_gracefully(self):
        """Test that empty/minimal JSON doesn't cause errors."""
        post = create_post(created_by=self.user)

        # Minimal empty JSON
        content = {}
        metrics = {}

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        # Should not raise an exception
        score = feed_entry.calculate_hot_score_v2()

        # Should return valid integer (0 or low value)
        self.assertIsInstance(score, int)
        self.assertGreaterEqual(score, 0)

    def test_hot_score_breakdown_structure(self):
        """Test that hot score breakdown has correct structure and uses config."""
        from feed.hot_score import HOT_SCORE_CONFIG
        from feed.hot_score_breakdown import get_hot_score_breakdown

        post = create_post(created_by=self.user)

        content = {
            "id": post.id,
            "title": "Test Post",
            "bounties": [
                {
                    "id": 1,
                    "amount": "100.0000000000",
                    "status": "OPEN",
                    "expiration_date": (self.now + timedelta(days=10)).isoformat(),
                }
            ],
            "purchases": [{"id": 1, "amount": "50"}],
        }

        metrics = {
            "votes": 10,
            "replies": 3,
            "review_metrics": {"count": 1},
        }

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        # Calculate hot score to create breakdown in separate table
        feed_entry.calculate_hot_score_v2()

        breakdown = get_hot_score_breakdown(feed_entry)

        # Verify structure
        self.assertIn("equation", breakdown)
        self.assertIn("steps", breakdown)
        self.assertIn("signals", breakdown)
        self.assertIn("time_factors", breakdown)
        self.assertIn("calculation", breakdown)
        self.assertIn("config_snapshot", breakdown)

        # Verify signals match config
        self.assertIn("bounty", breakdown["signals"])
        self.assertIn("tip", breakdown["signals"])

        # Verify weights come from config
        bounty_weight = breakdown["signals"]["bounty"]["weight"]
        config_weight = HOT_SCORE_CONFIG["signals"]["bounty"]["weight"]
        self.assertEqual(bounty_weight, config_weight)

        # Verify equation is a non-empty string
        self.assertIsInstance(breakdown["equation"], str)
        self.assertGreater(len(breakdown["equation"]), 0)

        # Verify steps is a list
        self.assertIsInstance(breakdown["steps"], list)
        self.assertGreater(len(breakdown["steps"]), 0)

        # Verify breakdown is stored in separate table
        feed_entry.refresh_from_db()
        self.assertTrue(
            hasattr(feed_entry, "hot_score_breakdown_v2")
            and feed_entry.hot_score_breakdown_v2 is not None
        )
        self.assertEqual(breakdown, feed_entry.hot_score_breakdown_v2.breakdown_data)

    def test_breakdown_created_when_calculating_hot_score_v2(self):
        """Test HotScoreV2Breakdown is created when calculate_hot_score_v2 is called."""
        post = create_post(created_by=self.user)

        content = {"id": post.id, "title": "Test Post", "bounties": [], "purchases": []}
        metrics = {"votes": 10, "replies": 0, "review_metrics": {"count": 0}}

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        # Initially no breakdown should exist
        self.assertFalse(
            hasattr(feed_entry, "hot_score_breakdown_v2")
            and feed_entry.hot_score_breakdown_v2
        )

        # Calculate hot score
        score = feed_entry.calculate_hot_score_v2()

        # Verify breakdown was created
        feed_entry.refresh_from_db()
        self.assertTrue(
            hasattr(feed_entry, "hot_score_breakdown_v2")
            and feed_entry.hot_score_breakdown_v2 is not None
        )
        breakdown = feed_entry.hot_score_breakdown_v2
        self.assertIsInstance(breakdown, HotScoreV2Breakdown)
        self.assertEqual(breakdown.feed_entry_id, feed_entry.id)
        self.assertIn("calculation", breakdown.breakdown_data)
        self.assertEqual(breakdown.breakdown_data["calculation"]["final_score"], score)

    def test_breakdown_updated_on_recalculation(self):
        """Test that breakdown is updated when hot_score_v2 is recalculated."""
        post = create_post(created_by=self.user)

        content = {"id": post.id, "title": "Test Post", "bounties": [], "purchases": []}
        metrics = {"votes": 10, "replies": 0, "review_metrics": {"count": 0}}

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        # Calculate first time
        score1 = feed_entry.calculate_hot_score_v2()
        breakdown_id_1 = feed_entry.hot_score_breakdown_v2.id

        # Update metrics to change score
        feed_entry.metrics = {
            "votes": 100,
            "replies": 0,
            "review_metrics": {"count": 0},
        }
        feed_entry.save()

        # Recalculate
        score2 = feed_entry.calculate_hot_score_v2()

        # Verify same breakdown object was updated (not recreated)
        feed_entry.refresh_from_db()
        breakdown_id_2 = feed_entry.hot_score_breakdown_v2.id
        self.assertEqual(breakdown_id_1, breakdown_id_2)

        # Verify breakdown data was updated
        self.assertEqual(
            feed_entry.hot_score_breakdown_v2.breakdown_data["calculation"][
                "final_score"
            ],
            score2,
        )
        self.assertNotEqual(score1, score2)

    def test_breakdown_deleted_when_no_item(self):
        """Test that breakdown is deleted when feed entry has no item."""
        post = create_post(created_by=self.user)

        content = {"id": post.id, "title": "Test Post", "bounties": [], "purchases": []}
        metrics = {"votes": 10, "replies": 0, "review_metrics": {"count": 0}}

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        # Create a breakdown first
        feed_entry.calculate_hot_score_v2()
        self.assertIsNotNone(feed_entry.hot_score_breakdown_v2)
        breakdown_id = feed_entry.hot_score_breakdown_v2.id

        # Delete the post (simulate item being deleted)
        post.delete()

        # Recalculate - should delete breakdown since item is now None
        feed_entry.refresh_from_db()
        feed_entry.calculate_hot_score_v2()

        # Verify breakdown was deleted
        feed_entry.refresh_from_db()
        self.assertFalse(HotScoreV2Breakdown.objects.filter(id=breakdown_id).exists())

    def test_breakdown_one_to_one_relationship(self):
        """Test that OneToOneField relationship works correctly."""
        post = create_post(created_by=self.user)

        content = {"id": post.id, "title": "Test Post", "bounties": [], "purchases": []}
        metrics = {"votes": 10, "replies": 0, "review_metrics": {"count": 0}}

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        feed_entry.calculate_hot_score_v2()

        # Verify relationship
        breakdown = feed_entry.hot_score_breakdown_v2
        self.assertEqual(breakdown.feed_entry, feed_entry)
        self.assertEqual(breakdown.feed_entry_id, feed_entry.id)

        # Verify we can access feed_entry from breakdown
        self.assertEqual(breakdown.feed_entry.id, feed_entry.id)

        # Verify only one breakdown per feed_entry (unique constraint)
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            HotScoreV2Breakdown.objects.create(
                feed_entry=feed_entry,
                breakdown_data={"test": "data"},
            )

    def test_breakdown_str_representation(self):
        """Test HotScoreV2Breakdown __str__ method."""
        post = create_post(created_by=self.user)

        content = {"id": post.id, "title": "Test Post", "bounties": [], "purchases": []}
        metrics = {"votes": 10, "replies": 0, "review_metrics": {"count": 0}}

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        feed_entry.calculate_hot_score_v2()

        breakdown = feed_entry.hot_score_breakdown_v2
        str_repr = str(breakdown)
        self.assertIn(str(feed_entry.id), str_repr)
        self.assertIn("HotScoreV2Breakdown", str_repr)

    def test_breakdown_deleted_when_no_calc_data(self):
        """Test that breakdown is deleted when calculation returns no data."""
        post = create_post(created_by=self.user)

        content = {"id": post.id, "title": "Test Post", "bounties": [], "purchases": []}
        metrics = {"votes": 10, "replies": 0, "review_metrics": {"count": 0}}

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        # Create a breakdown first
        feed_entry.calculate_hot_score_v2()
        breakdown_id = feed_entry.hot_score_breakdown_v2.id

        # Mock calculate_hot_score to return None (no calc_data)
        from unittest.mock import patch

        with patch("feed.hot_score.calculate_hot_score", return_value=None):
            feed_entry.calculate_hot_score_v2()

        # Verify breakdown was deleted
        feed_entry.refresh_from_db()
        self.assertFalse(HotScoreV2Breakdown.objects.filter(id=breakdown_id).exists())

    def test_breakdown_deleted_on_exception(self):
        """Test that breakdown is deleted when exception occurs during calculation."""
        post = create_post(created_by=self.user)

        content = {"id": post.id, "title": "Test Post", "bounties": [], "purchases": []}
        metrics = {"votes": 10, "replies": 0, "review_metrics": {"count": 0}}

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        # Create a breakdown first
        feed_entry.calculate_hot_score_v2()
        breakdown_id = feed_entry.hot_score_breakdown_v2.id

        # Mock calculate_hot_score to raise an exception, and
        # calculate_hot_score_for_item to return a fallback score
        from unittest.mock import patch

        with (
            patch(
                "feed.hot_score.calculate_hot_score",
                side_effect=ValueError("Test error"),
            ),
            patch("feed.models.calculate_hot_score_for_item", return_value=42),
        ):
            # Should not raise, should handle gracefully
            score = feed_entry.calculate_hot_score_v2()
            self.assertEqual(score, 42)

        # Verify breakdown was deleted on error
        feed_entry.refresh_from_db()
        self.assertFalse(HotScoreV2Breakdown.objects.filter(id=breakdown_id).exists())

    def test_breakdown_handles_object_does_not_exist(self):
        """Test ObjectDoesNotExist exception is handled when breakdown doesn't exist."""
        post = create_post(created_by=self.user)

        content = {"id": post.id, "title": "Test Post", "bounties": [], "purchases": []}
        metrics = {"votes": 10, "replies": 0, "review_metrics": {"count": 0}}

        feed_entry = FeedEntry.objects.create(
            item=post,
            unified_document=post.unified_document,
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=content,
            metrics=metrics,
        )

        # Ensure no breakdown exists initially
        from django.core.exceptions import ObjectDoesNotExist

        with self.assertRaises(ObjectDoesNotExist):
            _ = feed_entry.hot_score_breakdown_v2

        # Delete the post to trigger the "no item" path
        # This should handle ObjectDoesNotExist gracefully
        post.delete()

        # This should not raise ObjectDoesNotExist - should handle gracefully
        feed_entry.refresh_from_db()
        score = feed_entry.calculate_hot_score_v2()
        self.assertEqual(score, 0)
