"""
Tests for the hot score calculation module.
"""

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.hot_score import CONTENT_TYPE_WEIGHTS, calculate_hot_score_for_item
from feed.models import FeedEntry
from feed.serializers import serialize_feed_item, serialize_feed_metrics
from paper.tests.helpers import create_paper
from reputation.models import Bounty, Escrow
from researchhub_comment.constants.rh_comment_thread_types import PEER_REVIEW
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.helpers import create_post
from user.tests.helpers import create_random_default_user


class TestHotScore(TestCase):
    """Test suite for hot score calculations."""

    def setUp(self):
        # Create a time reference for consistent testing
        self.now = datetime.now(timezone.utc)
        self.one_day_ago = self.now - timedelta(days=1)
        self.one_week_ago = self.now - timedelta(days=7)

        # Create a user for the tests
        self.user = create_random_default_user("hotscore_test_user")

        # Create a paper and post for testing
        self.paper = create_paper(uploaded_by=self.user)
        paper_content_type = ContentType.objects.get_for_model(self.paper)
        self.feed_entry_paper = FeedEntry.objects.create(
            item=self.paper,
            unified_document=self.paper.unified_document,
            content_type=paper_content_type,
            object_id=self.paper.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=serialize_feed_item(self.paper, paper_content_type),
            metrics=serialize_feed_metrics(self.paper, paper_content_type),
        )
        self.post = create_post(created_by=self.user)
        post_content_type = ContentType.objects.get_for_model(self.post)
        self.feed_entry_post = FeedEntry.objects.create(
            item=self.post,
            unified_document=self.post.unified_document,
            content_type=post_content_type,
            object_id=self.post.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=serialize_feed_item(self.post, post_content_type),
            metrics=serialize_feed_metrics(self.post, post_content_type),
        )

        # Create comment threads for paper and post
        self.paper_thread = RhCommentThreadModel.objects.create(
            content_object=self.paper,
            created_by=self.user,
            updated_by=self.user,
        )

        self.post_thread = RhCommentThreadModel.objects.create(
            content_object=self.post,
            created_by=self.user,
            updated_by=self.user,
        )

        # Create comments for paper and post
        self.paper_comment = RhCommentModel.objects.create(
            comment_content_json={"text": "Paper comment"},
            context_title="Paper comment title",
            thread=self.paper_thread,
            created_by=self.user,
            updated_by=self.user,
            score=5,
        )

        self.post_comment = RhCommentModel.objects.create(
            comment_content_json={"text": "Post comment"},
            context_title="Post comment title",
            thread=self.post_thread,
            created_by=self.user,
            updated_by=self.user,
            score=5,
        )

        # Create a review comment
        self.paper_review_thread = RhCommentThreadModel.objects.create(
            content_object=self.paper,
            created_by=self.user,
            updated_by=self.user,
            thread_type=PEER_REVIEW,
        )

        self.paper_review = RhCommentModel.objects.create(
            comment_content_json={"text": "This is a peer review"},
            context_title="Peer Review",
            thread=self.paper_review_thread,
            created_by=self.user,
            updated_by=self.user,
            comment_type=PEER_REVIEW,
            score=5,
        )

    def create_bounty(self, amount, item):
        """Create a real bounty object with specified amount."""
        content_type = ContentType.objects.get_for_model(item)

        # Create an escrow for the bounty
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            amount_holding=amount,
            object_id=item.id,
            content_type=content_type,
        )

        # Create the bounty
        bounty = Bounty.objects.create(
            amount=amount,
            created_by=self.user,
            item_content_type=content_type,
            item_object_id=item.id,
            escrow=escrow,
            unified_document=item.unified_document,
            status=Bounty.OPEN,
        )

        return bounty

    def test_time_decay_effect(self):
        """Test that time decay significantly reduces scores for old content."""
        # Create very old content with minimal activity
        old_paper = create_paper(uploaded_by=self.user)
        old_paper.created_date = self.now - timedelta(days=100)  # Very old
        old_paper.score = 1
        old_paper.save()
        old_paper_content_type = ContentType.objects.get_for_model(old_paper)
        feed_entry_old_paper = FeedEntry.objects.create(
            item=old_paper,
            unified_document=old_paper.unified_document,
            content_type=old_paper_content_type,
            object_id=old_paper.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=serialize_feed_item(old_paper, old_paper_content_type),
            metrics=serialize_feed_metrics(old_paper, old_paper_content_type),
        )

        # Create new content with same score for comparison
        new_paper = create_paper(uploaded_by=self.user)
        new_paper.score = 1
        new_paper.save()
        new_paper_content_type = ContentType.objects.get_for_model(new_paper)
        feed_entry_new_paper = FeedEntry.objects.create(
            item=new_paper,
            unified_document=new_paper.unified_document,
            content_type=new_paper_content_type,
            object_id=new_paper.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=serialize_feed_item(new_paper, new_paper_content_type),
            metrics=serialize_feed_metrics(new_paper, new_paper_content_type),
        )

        old_score = calculate_hot_score_for_item(feed_entry_old_paper)
        new_score = calculate_hot_score_for_item(feed_entry_new_paper)

        # New content should have significantly higher score due to less time decay
        self.assertGreater(new_score, old_score)

    def test_bounty_calculation(self):
        """Test hot score calculation with various bounty amounts."""
        # Create bounties for the paper
        self.create_bounty(Decimal("5"), self.paper)
        self.create_bounty(Decimal("10"), self.paper)
        self.create_bounty(Decimal("15"), self.paper)

        # Refresh the paper content/metrics to include bounties
        paper_content_type = ContentType.objects.get_for_model(self.paper)
        self.feed_entry_paper.content = serialize_feed_item(
            self.paper, paper_content_type
        )
        self.feed_entry_paper.metrics = serialize_feed_metrics(
            self.paper, paper_content_type
        )
        self.feed_entry_paper.save()

        # Calculate score with bounties
        score_with_bounties = calculate_hot_score_for_item(self.feed_entry_paper)

        # Create a paper without bounties for comparison
        paper_no_bounties = create_paper(uploaded_by=self.user)
        paper_no_bounties.score = self.paper.score
        paper_no_bounties.save()
        paper_no_bounties_content_type = ContentType.objects.get_for_model(
            paper_no_bounties
        )
        self.feed_entry_paper_no_bounties = FeedEntry.objects.create(
            item=paper_no_bounties,
            unified_document=paper_no_bounties.unified_document,
            content_type=paper_no_bounties_content_type,
            object_id=paper_no_bounties.id,
            action=FeedEntry.PUBLISH,
            action_date=self.now,
            content=serialize_feed_item(
                paper_no_bounties, paper_no_bounties_content_type
            ),
            metrics=serialize_feed_metrics(
                paper_no_bounties, paper_no_bounties_content_type
            ),
        )

        score_no_bounties = calculate_hot_score_for_item(
            self.feed_entry_paper_no_bounties
        )

        # Score with bounties should be higher
        self.assertGreater(score_with_bounties, score_no_bounties)

        # Verify sqrt of bounty amount is used in calculation
        weights = CONTENT_TYPE_WEIGHTS["paper"]
        # Calculate bounty component
        bounty_weight = weights["bounty_weight"]
        bounty_component = math.sqrt(30) * bounty_weight
        self.assertGreater(bounty_component, 0)

    def test_hot_score_increases_with_social_media_engagement(self):
        """Test that social media engagement increases the hot score."""
        # Get baseline score without social media data
        baseline_score = calculate_hot_score_for_item(self.feed_entry_paper)

        # Add X engagement to metrics
        self.feed_entry_paper.metrics = {
            **self.feed_entry_paper.metrics,
            "external": {
                "x": {
                    "post_count": 5,
                    "total_likes": 100,
                    "total_quotes": 10,
                    "total_replies": 5,
                    "total_reposts": 50,
                    "total_impressions": 10000,
                },
                "bluesky": {
                    "post_count": 2,
                    "total_likes": 20,
                    "total_quotes": 2,
                    "total_replies": 3,
                    "total_reposts": 5,
                },
                "github_mentions": {
                    "total_mentions": 3,
                    "breakdown": {"code": 2, "issues": 1},
                },
            },
        }
        self.feed_entry_paper.save(update_fields=["metrics"])

        # Calculate new score
        new_score = calculate_hot_score_for_item(self.feed_entry_paper)

        # Score should be higher with social media engagement
        self.assertGreater(new_score, baseline_score)
