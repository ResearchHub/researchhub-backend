from time import time

from django.contrib.admin.options import get_content_type_for_model
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

import reputation.distributions as distributions
from discussion.lib import check_is_discussion_item
from discussion.models import Comment, Reply, Thread
from discussion.models import Vote as GrmVote
from paper.models import Paper
from reputation.distributor import Distributor
from reputation.exceptions import ReputationSignalError
from reputation.models import Distribution
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from utils import sentry

NEW_USER_BONUS_REPUTATION_LIMIT = 200
NEW_USER_BONUS_DAYS_LIMIT = 30


@receiver(
    m2m_changed,
    sender=ResearchhubUnifiedDocument.hubs.through,
    dispatch_uid="unified_doc_hubs_changed",
)
def update_distribution_for_hub_changes(
    sender, instance, action, reverse, model, pk_set, **kwargs
):
    if (
        (action == "post_add")
        and pk_set is not None
        and instance.document_type == "PAPER"
    ):
        distributions = Distribution.objects.filter(
            proof_item_object_id=instance.paper.id,
            proof_item_content_type=get_content_type_for_model(instance.paper),
        )
        for distribution in distributions:
            distribution.hubs.add(*instance.hubs.all())


@receiver(post_delete, sender=Paper, dispatch_uid="censor_paper")
def distribute_for_censor_paper(sender, instance, using, **kwargs):
    timestamp = time()
    flags = instance.flags.select_related("created_by").all()
    for flag in flags:
        recipient = flag.created_by
        if is_eligible_user(recipient):
            distributor = Distributor(
                distributions.FlagPaper,
                recipient,
                instance,
                timestamp,
                instance.created_by,
                instance.hubs.all(),
            )
            record = distributor.distribute()


@receiver(post_save, sender=Comment, dispatch_uid="censor_comment")
@receiver(post_save, sender=Reply, dispatch_uid="censor_reply")
@receiver(post_save, sender=Thread, dispatch_uid="censor_thread")
@receiver(post_save, sender=RhCommentModel, dispatch_uid="censor_rh_comment")
def distribute_for_censor(sender, instance, created, update_fields, **kwargs):
    timestamp = time()
    distributor = None
    hubs = None

    if check_censored(created, update_fields) is True:
        try:
            if check_is_discussion_item(instance):
                distribution = get_discussion_censored_distribution(instance)
                recipient = instance.created_by
                hubs = get_discussion_hubs(instance)

            else:
                raise TypeError

            all_hubs = None
            if hubs is not None:
                all_hubs = hubs.all()

            if is_eligible_user(recipient):
                distributor = Distributor(
                    distribution,
                    recipient,
                    instance,
                    timestamp,
                    instance.created_by,
                    all_hubs,
                )

        except TypeError as e:
            error = ReputationSignalError(e, "Failed to distribute")
            print(error)
            sentry.log_error(error)

    if distributor is not None:
        distributor.distribute()


def check_censored(created, update_fields):
    return not created and (update_fields is not None) and ("censor" in update_fields)


def get_discussion_censored_distribution(instance):
    item_type = type(instance)

    error = TypeError(f"Instance of type {item_type} is not supported")

    if item_type == Comment:
        return distributions.CommentCensored
    elif item_type == Reply:
        return distributions.ReplyCensored
    elif item_type == Thread:
        return distributions.ThreadCensored
    elif item_type == ResearchhubPost:
        return distributions.ResearchhubPostCensored
    else:
        raise error


def get_discussion_hubs(instance):
    hubs = None
    if isinstance(instance, Comment):
        hubs = instance.parent.paper.hubs
    elif isinstance(instance, Reply):
        try:
            hubs = instance.parent.parent.paper.hubs
        except Exception as e:
            sentry.log_error(e)
    elif isinstance(instance, Thread):
        hubs = instance.paper.hubs
    return hubs


@receiver(post_save, sender=GrmVote, dispatch_uid="discussion_vote")
def distribute_for_discussion_vote(sender, instance, created, update_fields, **kwargs):
    """Distributes reputation to the creator of the item voted on."""
    timestamp = time()
    distributor = None
    try:
        instance_item = instance.item
        if isinstance(instance_item, Paper):
            return
        else:
            recipient = instance.item.created_by
    except Exception as e:
        error = ReputationSignalError(e, "Invalid recipient")
        sentry.log_error(e)
        return

    voter = instance.created_by
    if (
        created or vote_type_updated(update_fields)
    ) and is_eligible_for_discussion_vote(recipient, voter):
        hubs = None
        item = instance.item
        if isinstance(item, RhCommentModel):
            hubs = item.thread.content_object.unified_document.hubs
        elif isinstance(item, Paper):
            hubs = item.hubs
        elif isinstance(item, ResearchhubPost):
            hubs = item.unified_document.hubs

        # TODO: This needs to be altered so that if the vote changes the
        # original distribution is deleted if not yet withdrawn

        if created:
            try:
                # NOTE: Only comment seems to be supporting distribution
                distribution = get_discussion_vote_item_distribution(instance)
                distributor = Distributor(
                    distribution,
                    recipient,
                    instance,
                    timestamp,
                    instance.created_by,
                    hubs.all(),
                )
            except TypeError as e:
                error = ReputationSignalError(
                    e, "Failed to distribute for reaction vote"
                )
                sentry.log_error(error)

    if distributor is not None and recipient != instance.created_by:
        record = distributor.distribute()


def is_eligible_for_discussion_vote(recipient, voter):
    """
    Returns True if the recipient is eligible to receive an award.

    Checks to ensure recipient is not also the voter.
    """
    if voter is None:
        return True
    return (recipient != voter) and is_eligible_user(recipient)


def is_eligible_user(user):
    if user is not None:
        return user.is_active and not user.is_suspended
    return False


def vote_type_updated(update_fields):
    if update_fields is not None:
        return "vote_type" in update_fields
    return False


def get_discussion_vote_item_distribution(instance):
    vote_type = instance.vote_type
    item = instance.item
    item_type = type(item)

    error = TypeError(f"Instance of type {item_type} is not supported")
    if vote_type == GrmVote.UPVOTE:
        if isinstance(item, RhCommentModel):
            return distributions.RhCommentUpvoted
        elif isinstance(item, ResearchhubPost):
            return distributions.ResearchhubPostUpvoted
        elif isinstance(item, Paper):
            return distributions.PaperUpvoted
        else:
            raise error

    elif vote_type == GrmVote.DOWNVOTE:
        if isinstance(item, RhCommentModel):
            vote_type = distributions.RhCommentDownvoted
            return distributions.ThreadDownvoted
        elif isinstance(item, ResearchhubPost):
            return distributions.ResearchhubPostDownvoted
        elif isinstance(item, Paper):
            return distributions.PaperDownvoted
        else:
            raise error
    elif vote_type == GrmVote.NEUTRAL:
        return distributions.NeutralVote


@receiver(post_delete, sender=Distribution, dispatch_uid="delete_distribution")
def revoke_reputation(sender, instance, **kwargs):
    # TODO: Use F expression here to avoid race conditions
    recipient = instance.recipient
    amount = instance.amount
    current = recipient.reputation
    recipient.reputation = current - amount
    recipient.save(update_fields=["reputation"])
