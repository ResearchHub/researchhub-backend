"""
Integration tests for hot score v2 (JSON-based) algorithm.

These tests validate that the hot score calculation uses FeedEntry.content
and FeedEntry.metrics JSON fields instead of querying related models.
"""

from datetime import datetime, timedelta, timezone

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.models import FeedEntry
from researchhub_document.helpers import create_post
from user.tests.helpers import create_random_default_user


class TestHotScoreV2(TestCase):
    """Integration tests for hot score v2 (JSON-based) algorithm."""

    def setUp(self):
        """Set up test fixtures."""
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

    def test_freshness_boost_new_vs_old_posts(self):
        """Test that new posts get 4.5x freshness boost vs old posts."""
        # Create new post
        new_post = create_post(created_by=self.user)

        # Create old post (50 hours ago, past the 48h cutoff)
        old_post = create_post(created_by=self.user)
        old_created = self.now - timedelta(hours=50)

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

        # New post should have significantly higher score
        # Even accounting for time decay, freshness boost should be evident
        self.assertGreater(new_score, old_score * 2)

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
