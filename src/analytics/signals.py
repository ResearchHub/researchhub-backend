from django.db.models.signals import post_save
from django.dispatch import receiver

from discussion.models import Vote
from paper.models import PaperSubmission
from purchase.related_models.purchase_model import Purchase
from reputation.related_models.bounty import Bounty
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from review.models.review_model import Review

from .amplitude import UserActivityTypes, track_user_activity


@receiver(post_save, sender=Vote, dispatch_uid="track_vote_activity")
def track_vote_activity(sender, instance, created, **kwargs):
    """
    Track upvote activity when a vote is created.
    Only track upvotes, not downvotes or neutral votes.
    """
    if created and instance.vote_type == Vote.UPVOTE:
        track_user_activity(
            user=instance.created_by,
            activity_type=UserActivityTypes.UPVOTE,
            additional_properties={
                "vote_id": instance.id,
                "content_type": instance.content_type.model,
                "object_id": instance.object_id,
            },
        )


@receiver(post_save, sender=RhCommentModel, dispatch_uid="track_comment_activity")
def track_comment_activity(sender, instance, created, **kwargs):
    """
    Track comment activity when a comment is created.
    Skip peer review comments as they are handled separately.
    """
    if created and instance.is_public and not instance.is_removed:
        # Skip peer review comments - they will be tracked in peer review tracking
        if instance.comment_type == "PEER_REVIEW":
            return

        track_user_activity(
            user=instance.created_by,
            activity_type=UserActivityTypes.COMMENT,
            additional_properties={
                "comment_id": instance.id,
                "comment_type": instance.comment_type,
                "thread_id": instance.thread.id,
                "content_type": instance.thread.content_type.model,
                "object_id": instance.thread.object_id,
            },
        )


@receiver(post_save, sender=Review, dispatch_uid="track_peer_review_activity")
def track_peer_review_activity(sender, instance, created, **kwargs):
    """
    Track peer review activity when a review is created.
    This handles the case where a review comment is created and then a review is set.
    """
    if created:
        track_user_activity(
            user=instance.created_by,
            activity_type=UserActivityTypes.PEER_REVIEW,
            additional_properties={
                "review_id": instance.id,
                "score": instance.score,
                "content_type": instance.content_type.model,
                "object_id": instance.object_id,
            },
        )


@receiver(post_save, sender=Purchase, dispatch_uid="track_fund_activity")
def track_fund_activity(sender, instance, created, **kwargs):
    """
    Track funding activity when a purchase is created.
    Only track fundraise contributions, not other purchase types.
    """
    if created and instance.purchase_type == "FUNDRAISE_CONTRIBUTION":
        track_user_activity(
            user=instance.user,
            activity_type=UserActivityTypes.FUND,
            additional_properties={
                "purchase_id": instance.id,
                "amount": instance.amount,
                "purchase_method": instance.purchase_method,
                "content_type": instance.content_type.model,
                "object_id": instance.object_id,
            },
        )


@receiver(post_save, sender=Bounty, dispatch_uid="track_tip_activity")
def track_tip_activity(sender, instance, created, **kwargs):
    """
    Track tip activity when a bounty is created.
    Only track non-review bounties as tips.
    """
    if created and instance.bounty_type != Bounty.Type.REVIEW:
        track_user_activity(
            user=instance.created_by,
            activity_type=UserActivityTypes.TIP,
            additional_properties={
                "bounty_id": instance.id,
                "amount": str(instance.amount),
                "bounty_type": instance.bounty_type,
                "content_type": instance.item_content_type.model,
                "object_id": instance.item_object_id,
            },
        )


@receiver(
    post_save, sender=PaperSubmission, dispatch_uid="track_journal_submission_activity"
)
def track_journal_submission_activity(sender, instance, created, **kwargs):
    """
    Track journal submission activity when a paper submission is created.
    Only track when the submission is initiated (not when it's completed).
    """
    if created and instance.paper_status == PaperSubmission.INITIATED:
        track_user_activity(
            user=instance.uploaded_by,
            activity_type=UserActivityTypes.JOURNAL_SUBMISSION,
            additional_properties={
                "submission_id": instance.id,
                "paper_status": instance.paper_status,
                "doi": instance.doi,
                "url": instance.url,
            },
        )
