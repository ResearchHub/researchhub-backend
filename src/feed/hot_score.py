import datetime
import math

from django.db.models import FloatField, Sum

from discussion.reaction_models import Vote as GrmVote
from paper.related_models.paper_model import Paper
from purchase.models import Purchase
from researchhub_comment.models import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost


def calculate_vote_score(item, content_type):
    """
    Calculate the vote score component for an item
    """
    if hasattr(item, "score"):
        # Direct score attribute exists
        return item.score
    else:
        # Fallback to calculating from votes
        upvotes = GrmVote.objects.filter(
            content_type=content_type, object_id=item.id, vote_type=GrmVote.UPVOTE
        ).count()

        downvotes = GrmVote.objects.filter(
            content_type=content_type, object_id=item.id, vote_type=GrmVote.DOWNVOTE
        ).count()

        return upvotes - downvotes


def calculate_comment_score(item, content_type):
    """
    Calculate the comment/reply activity score
    """
    comment_count = 0

    if isinstance(item, Paper):
        # Count threads and comments for papers
        comment_count = item.rh_threads.get_discussion_count()
    elif isinstance(item, ResearchhubPost):
        # Count comments for posts
        comment_count = item.rh_threads.get_discussion_count()
    elif isinstance(item, RhCommentModel):
        # Count replies for comments
        comment_count = item.replies.count()

    return comment_count


def calculate_tip_score(item, content_type):
    """
    Calculate the tip score from RSC tips/purchases
    """
    if hasattr(item, "purchases"):
        # Sum up the RSC amounts from purchases
        purchases = item.purchases.filter(paid_status=Purchase.PAID, amount__gt=0)

        if purchases.exists():
            total_amount = purchases.aggregate(
                total=Sum("amount", output_field=FloatField())
            ).get("total", 0)

            return float(total_amount)

    return 0


def calculate_time_decay(created_date):
    """
    Calculate time decay factor to prioritize recent content

    Base decay for half-life of 3 days (how long it takes for a post to lose half its
    value)
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    age_in_hours = (now - created_date).total_seconds() / 3600

    # Decay factor: smaller values for older content
    # Half-life of 72 hours (3 days)
    # Using ln(2)/72 as decay rate gives a half-life of exactly 3 days
    decay_factor = math.exp(-(math.log(2) / 72) * age_in_hours)

    return decay_factor


def calculate_hot_score(feed_entry):
    """
    Calculate hot score for a feed entry

    hot_score = (base_score + activity_score + boosted_score) * time_decay * 1000
    """
    content_type = feed_entry.content_type
    item = feed_entry.item

    if item is None:
        return 0

    # Get vote score
    vote_score = calculate_vote_score(item, content_type)
    base_score = math.log(abs(vote_score) + 1, 2) * (1 if vote_score >= 0 else -1)

    # Get comment activity score
    comment_count = calculate_comment_score(item, content_type)
    comment_score = math.log(comment_count + 1, 2)

    # Get tip score
    tip_amount = calculate_tip_score(item, content_type)
    tip_score = math.log(tip_amount + 1, 4)

    # Calculate time decay
    time_decay = calculate_time_decay(feed_entry.action_date)

    # Combine scores
    activity_score = comment_score + tip_score

    # Adjust weights based on content type
    content_type_model = content_type.model.lower()
    if content_type_model == "paper":
        # Papers get a slight boost
        content_type_weight = 1.2
    elif content_type_model == "researchhubpost":
        # Posts get normal weight
        content_type_weight = 1.0
    elif content_type_model == "rhcommentmodel":
        # Comments get a reduced weight
        content_type_weight = 0.7
    else:
        content_type_weight = 1.0

    # Calculate final hot score
    combined_score = (base_score + activity_score) * content_type_weight
    hot_score = combined_score * time_decay * 1000

    return int(hot_score)


def update_feed_entry_hot_score(feed_entry):
    """
    Calculate and update the hot score for a feed entry
    """
    hot_score = calculate_hot_score(feed_entry)
    feed_entry.hot_score = hot_score
    feed_entry.save(update_fields=["hot_score", "updated_date"])
    return hot_score


def recalculate_all_hot_scores(batch_size=1000):
    """
    Recalculate hot scores for all feed entries in batches
    """
    from feed.models import FeedEntry

    total = FeedEntry.objects.count()
    processed = 0

    while processed < total:
        batch_end = processed + batch_size
        entries = FeedEntry.objects.all().order_by("id")[processed:batch_end]
        for entry in entries:
            update_feed_entry_hot_score(entry)

        processed += batch_size
        print(f"Processed {min(processed, total)}/{total} feed entries")
