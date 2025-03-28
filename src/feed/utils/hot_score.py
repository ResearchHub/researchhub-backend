import math
from datetime import datetime, timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver

from discussion.reaction_models import Vote
from paper.models import Paper
from reputation.related_models.bounty import Bounty
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost


def calculate_hot_score(feed_entry):
    """
    Calculate a hot score for a feed entry based on:
    - Vote score (upvotes - downvotes)
    - Number of comments/replies
    - Amount raised or in escrow (for bounties)
    - Time decay factor from action date

    Higher scores indicate "hotter" content.
    """
    item = feed_entry.item
    content_type = feed_entry.content_type.model

    # Base score starts at 0
    score = 0

    # Vote score component (upvotes - downvotes)
    if hasattr(item, "score"):
        vote_score = getattr(item, "score", 0)
        # Log transform to dampen the effect of extremely high vote counts
        if vote_score > 0:
            score += math.log(vote_score + 1) * 10
        else:
            score += vote_score  # Negative scores remain linear

    # Comments/discussions component
    if hasattr(item, "discussion_count"):
        comments = getattr(item, "discussion_count", 0)
        score += math.log(comments + 1) * 5  # Less weight than votes

    # For comments, count replies
    if content_type == "rhcommentmodel" and hasattr(item, "children_count"):
        replies = getattr(item, "children_count", 0)
        score += math.log(replies + 1) * 3

    # For bounties, factor in monetary value
    if content_type == "bounty":
        # Sum all amounts from bounty contributions
        bounty_amount = 0
        if hasattr(item, "amount"):
            bounty_amount = item.amount
        elif hasattr(item, "bounties"):
            bounty_amount = sum(b.amount for b in item.bounties.all())

        # Monetary value has significant weight
        score += math.log(bounty_amount + 1) * 15

    # Time decay factor - newer content ranks higher
    # Calculate hours since action_date
    now = datetime.now(feed_entry.action_date.tzinfo)
    hours_age = max(1, (now - feed_entry.action_date).total_seconds() / 3600)

    # Apply time decay: score decays with the square root of time
    score = score / math.sqrt(hours_age)

    return score


def update_feed_entry_hot_score(sender, instance, **kwargs):
    """Update hot score for feed entries related to the changed object"""
    from feed.models import FeedEntry  # Import here to avoid circular imports

    # Get ContentType for the instance
    content_type = ContentType.objects.get_for_model(instance)

    # Find all feed entries referencing this object
    feed_entries = FeedEntry.objects.filter(
        content_type=content_type, object_id=instance.id
    )

    # Update hot score for each entry
    for entry in feed_entries:
        entry.hot_score = calculate_hot_score(entry)
        entry.save(update_fields=["hot_score"])


# Signal receivers for various models that affect hot scores
@receiver(post_save, sender=Vote)
def update_hot_score_on_vote(sender, instance, **kwargs):
    """Update hot score when a vote changes"""
    # The vote affects the hot score of the voted object
    if instance.content_object:
        # Get ContentType and object_id of the voted object
        content_type = ContentType.objects.get_for_model(instance.content_object)
        object_id = instance.content_object.id

        from feed.models import FeedEntry  # Import here to avoid circular imports

        # Find feed entries for the voted object
        feed_entries = FeedEntry.objects.filter(
            content_type=content_type, object_id=object_id
        )

        # Update hot score for each entry
        for entry in feed_entries:
            entry.hot_score = calculate_hot_score(entry)
            entry.save(update_fields=["hot_score"])


@receiver(post_save, sender=RhCommentModel)
def update_hot_score_on_comment(sender, instance, **kwargs):
    """Update hot score when a comment changes"""
    # For new comments or replies, this affects parent document's hot score
    if instance.unified_document:
        from feed.models import FeedEntry  # Import here to avoid circular imports

        # Update feed entries for the document
        feed_entries = FeedEntry.objects.filter(
            unified_document=instance.unified_document
        )

        for entry in feed_entries:
            entry.hot_score = calculate_hot_score(entry)
            entry.save(update_fields=["hot_score"])

    # This also affects the hot score of any parent comment
    if instance.parent_id:
        # Get the parent comment
        try:
            parent = RhCommentModel.objects.get(id=instance.parent_id)
            # Update feed entries for the parent comment
            update_feed_entry_hot_score(sender, parent)
        except RhCommentModel.DoesNotExist:
            pass


@receiver(post_save, sender=Bounty)
def update_hot_score_on_bounty(sender, instance, **kwargs):
    """Update hot score when a bounty changes"""
    update_feed_entry_hot_score(sender, instance)

    # If the bounty is on a comment, also update the comment's hot score
    if instance.item_content_type == ContentType.objects.get_for_model(RhCommentModel):
        update_feed_entry_hot_score(sender, instance.item)


# Connect signals for other model changes that should affect hot score
# (Paper updates, Post updates, etc.)
@receiver(post_save, sender=Paper)
def update_hot_score_on_paper_change(sender, instance, **kwargs):
    update_feed_entry_hot_score(sender, instance)


@receiver(post_save, sender=ResearchhubPost)
def update_hot_score_on_post_change(sender, instance, **kwargs):
    update_feed_entry_hot_score(sender, instance)


@app.task
def update_hot_scores():
    """Periodically update hot scores to ensure time decay applies consistently"""
    from feed.models import FeedEntry
    from feed.utils.hot_score import calculate_hot_score

    # Either update all entries or limit to recent/visible ones
    # For example, entries from the last 30 days or top 1000 by hot_score
    entries = FeedEntry.objects.filter(
        action_date__gte=datetime.now() - timedelta(days=30)
    ).order_by("-hot_score")[:1000]

    for entry in entries:
        entry.hot_score = calculate_hot_score(entry)
        entry.save(update_fields=["hot_score"])
