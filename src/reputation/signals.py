from datetime import timedelta
from time import time

from django.db.models import Q
from django.db.models.signals import m2m_changed, post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.contrib.admin.options import get_content_type_for_model

import reputation.distributions as distributions
from bullet_point.models import (
    BulletPoint,
    Vote as BulletPointVote
)
from discussion.lib import check_is_discussion_item
from discussion.models import (
    Comment,
    Reply,
    Thread,
    Vote as DiscussionVote
)
from paper.models import (
    Paper,
    Vote as PaperVote
)
from reputation.distributor import Distributor
from reputation.exceptions import ReputationSignalError
from reputation.models import Distribution
from summary.models import Summary, Vote as SummaryVote
from utils import sentry

# TODO: "Suspend" user if their reputation becomes negative
# This could mean setting `is_active` to false

NEW_USER_BONUS_REPUTATION_LIMIT = 200
NEW_USER_BONUS_DAYS_LIMIT = 30


@receiver(
    m2m_changed,
    sender=Paper.hubs.through,
    dispatch_uid='paper_hubs_changed'
)
def update_distribution_for_hub_changes(
    sender,
    instance,
    action,
    reverse,
    model,
    pk_set,
    **kwargs
):
    if (action == "post_add") and pk_set is not None:
        distributions = Distribution.objects.filter(
            proof_item_object_id=instance.id,
            proof_item_content_type=get_content_type_for_model(instance)
        )
        for distribution in distributions:
            distribution.hubs.add(*instance.hubs.all())


@receiver(post_save, sender=PaperVote, dispatch_uid='paper_upvoted')
def distribute_for_paper_upvoted(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    """Distributes reputation to the uploader."""
    timestamp = time()
    recipient = instance.paper.uploaded_by

    if is_eligible_for_paper_upvoted(
        created,
        instance.created_by,
        recipient
    ):
        distributor = Distributor(
            distributions.PaperUpvoted,
            recipient,
            instance,
            timestamp,
            instance.paper.hubs.all(),
        )
        record = distributor.distribute()


def is_eligible_for_paper_upvoted(created, voter, paper_uploader):
    return (
        created
        and is_eligible_user(paper_uploader)
        and (voter != paper_uploader)
    )


@receiver(post_delete, sender=Paper, dispatch_uid='censor_paper')
def distribute_for_censor_paper(
    sender,
    instance,
    using,
    **kwargs
):
    timestamp = time()
    flags = instance.flags.select_related('created_by').all()
    for flag in flags:
        recipient = flag.created_by
        if is_eligible_user(recipient):
            distributor = Distributor(
                distributions.FlagPaper,
                recipient,
                instance,
                timestamp,
                instance.hubs.all(),
            )
            record = distributor.distribute()


@receiver(post_save, sender=Summary, dispatch_uid='create_summary')
def distribute_for_create_summary(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    timestamp = time()
    recipient = instance.proposed_by

    if is_eligible_for_create_summary(created, recipient):
        distribution = distributions.CreateSummary
    elif is_eligible_for_create_first_summary(
        created,
        update_fields,
        instance
    ):
        distribution = distributions.CreateFirstSummary
    else:
        return

    last_distribution = recipient.reputation_records.filter(
        Q(distribution_type=distributions.CreateSummary)
        | Q(distribution_type=distributions.CreateFirstSummary)
    ).last()
    if check_summary_distribution_interval(last_distribution):
        distributor = Distributor(
            distribution,
            recipient,
            instance,
            timestamp,
            instance.paper.hubs.all(),
        )
        record = distributor.distribute()


@receiver(post_save, sender=SummaryVote, dispatch_uid='summary_vote')
def distribute_for_summary_vote(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    timestamp = time()
    voter = instance.created_by
    recipient = instance.summary.proposed_by

    if created and is_eligible_for_summary_vote(recipient, voter):
        hubs = instance.summary.paper.hubs
        distribution = get_summary_vote_item_distribution(instance)

        distributor = Distributor(
            distribution,
            recipient,
            instance,
            timestamp,
            hubs.all()
        )

        record = distributor.distribute()


def is_eligible_for_create_summary(created, user):
    return (
        created
        and is_eligible_user(user)
        and is_eligible_for_new_user_bonus(user)
    )


def is_eligible_for_create_first_summary(created, update_fields, summary):
    return (
        not created
        and check_approved_updated(update_fields)
        and summary.is_first_paper_summary
    )


def is_eligible_for_summary_vote(recipient, voter):
    """
    Returns True if the recipient is eligible to receive an award.

    Checks to ensure recipient is not also the voter.
    """
    if voter is None:
        return True
    return (recipient != voter) and is_eligible_user(recipient)


def get_summary_vote_item_distribution(instance):
    vote_type = instance.vote_type

    if vote_type == SummaryVote.UPVOTE:
        return distributions.SummaryUpvoted
    elif vote_type == SummaryVote.DOWNVOTE:
        return distributions.SummaryDownvoted
    else:
        raise TypeError('No vote type for summary instance')


def check_approved_updated(update_fields):
    if update_fields is not None:
        return 'approved' in update_fields
    return False


def check_summary_distribution_interval(distribution):
    """
    Returns True if distribution was created over an hour ago.
    """
    if not distribution:
        return True
    time_ago = timezone.now() - timedelta(hours=1)
    return distribution.created_date < time_ago


@receiver(post_save, sender=BulletPoint, dispatch_uid='create_bullet_point')
def distribute_for_create_bullet_point(sender, instance, created, **kwargs):
    timestamp = time()
    recipient = instance.created_by
    hubs = None
    if created and is_eligible_for_create_bullet_point(recipient):
        if (
            isinstance(instance, BulletPoint)
            and check_key_takeaway_interval(instance, recipient)
        ):
            distribution = distributions.CreateBulletPoint
            hubs = instance.paper.hubs
        else:
            return

        distributor = Distributor(
            distribution,
            recipient,
            instance,
            timestamp,
            hubs.all()
        )
        record = distributor.distribute()


@receiver(post_save, sender=BulletPointVote, dispatch_uid='bullet_point_vote')
def distribute_for_bullet_point_vote(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    timestamp = time()
    voter = instance.created_by
    recipient = instance.bulletpoint.created_by

    if created and is_eligible_for_bulletpoint_vote(recipient, voter):
        hubs = instance.bulletpoint.paper.hubs
        distribution = get_bulletpoint_vote_item_distribution(instance)

        distributor = Distributor(
            distribution,
            recipient,
            instance,
            timestamp,
            hubs.all()
        )

        record = distributor.distribute()


def is_eligible_for_create_bullet_point(user):
    return is_eligible_user(user) and is_eligible_for_new_user_bonus(user)


def is_eligible_for_bulletpoint_vote(recipient, voter):
    """
    Returns True if the recipient is eligible to receive an award.

    Checks to ensure recipient is not also the voter.
    """
    if voter is None:
        return True
    return (recipient != voter) and is_eligible_user(recipient)


def get_bulletpoint_vote_item_distribution(instance):
    vote_type = instance.vote_type

    if vote_type == BulletPointVote.UPVOTE:
        return distributions.BulletPointUpvoted
    elif vote_type == BulletPointVote.DOWNVOTE:
        return distributions.BulletPointDownvoted
    else:
        raise TypeError('No vote type for bulletpoint instance')


def check_key_takeaway_interval(bullet_point, recipient):
    if bullet_point.bullet_type == BulletPoint.BULLETPOINT_KEYTAKEAWAY:
        time_ago = timezone.now() - timedelta(hours=1)
        key_takeaway_count = recipient.bullet_points.filter(
            created_date__gte=time_ago,
            bullet_type=BulletPoint.BULLETPOINT_KEYTAKEAWAY
        ).count()
        if key_takeaway_count < 5:
            return True
    return False


def check_reply_to_other_creator(reply):
    return reply.parent.created_by is not reply.created_by


@receiver(post_save, sender=BulletPoint, dispatch_uid='censor_bullet_point')
@receiver(post_save, sender=Comment, dispatch_uid='censor_comment')
@receiver(post_save, sender=Reply, dispatch_uid='censor_reply')
@receiver(post_save, sender=Thread, dispatch_uid='censor_thread')
def distribute_for_censor(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    timestamp = time()
    distributor = None
    hubs = None

    if check_censored(created, update_fields) is True:
        try:
            if isinstance(instance, BulletPoint):
                distribution = distributions.BulletPointCensored
                recipient = instance.bullet_point.created_by
                hubs = instance.bullet_point.paper.hubs

            elif check_is_discussion_item(instance):
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
                    all_hubs
                )

        except TypeError as e:
            error = ReputationSignalError(
                e,
                'Failed to distribute'
            )
            print(error)

    if distributor is not None:
        distributor.distribute()


def check_censored(created, update_fields):
    return (
        not created
        and (update_fields is not None)
        and ('censor' in update_fields)
    )


def get_discussion_censored_distribution(instance):
    item_type = type(instance)

    error = TypeError(f'Instance of type {item_type} is not supported')

    if item_type == Comment:
        return distributions.CommentCensored
    elif item_type == Reply:
        return distributions.ReplyCensored
    elif item_type == Thread:
        return distributions.ThreadCensored
    else:
        raise error


def get_discussion_hubs(instance):
    hubs = None
    if isinstance(instance, BulletPoint):
        hubs = instance.paper.hubs
    elif isinstance(instance, Comment):
        hubs = instance.parent.paper.hubs
    elif isinstance(instance, Reply):
        try:
            hubs = instance.parent.parent.paper.hubs
        except Exception as e:
            sentry.log_error(e)
    elif isinstance(instance, Thread):
        hubs = instance.paper.hubs
    return hubs


@receiver(post_save, sender=DiscussionVote, dispatch_uid='discussion_vote')
def distribute_for_discussion_vote(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    """Distributes reputation to the creator of the item voted on."""
    timestamp = time()
    distributor = None
    try:
        recipient = instance.item.created_by
    except Exception as e:
        error = ReputationSignalError(e, 'Invalid recipient')
        print(error)
        return

    voter = instance.created_by

    if (
        created
        or vote_type_updated(update_fields)
    ) and is_eligible_for_discussion_vote(recipient, voter):
        hubs = None
        if isinstance(instance.item, Comment):
            hubs = instance.item.parent.paper.hubs
        elif isinstance(instance.item, Reply):
            try:
                hubs = instance.item.parent.parent.paper.hubs
            except Exception as e:
                sentry.log_error(e)
        elif isinstance(instance.item, Thread):
            hubs = instance.item.paper.hubs

        # TODO: This needs to be altered so that if the vote changes the
        # original distribution is deleted if not yet withdrawn
        try:
            distribution = get_discussion_vote_item_distribution(instance)
            distributor = Distributor(
                distribution,
                recipient,
                instance,
                timestamp,
                hubs.all()
            )
        except TypeError as e:
            error = ReputationSignalError(
                e,
                'Failed to distribute for discussion vote'
            )
            print(error)

    if distributor is not None:
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
        return 'vote_type' in update_fields
    return False


def get_discussion_flag_item_distribution(instance):
    item_type = type(instance.item)

    error = TypeError(f'Instance of type {item_type} is not supported')

    if item_type == Comment:
        return distributions.CommentFlagged
    elif item_type == Reply:
        return distributions.ReplyFlagged
    elif item_type == Thread:
        return distributions.ThreadFlagged
    else:
        raise error


def get_discussion_vote_item_distribution(instance):
    vote_type = instance.vote_type
    item = instance.item
    item_type = type(item)

    error = TypeError(f'Instance of type {item_type} is not supported')

    if vote_type == DiscussionVote.UPVOTE:
        if item_type == Comment:
            return distributions.CommentUpvoted
        elif item_type == Reply:
            return distributions.ReplyUpvoted
        elif item_type == Thread:
            return distributions.ThreadUpvoted
        else:
            raise error

    elif vote_type == DiscussionVote.DOWNVOTE:
        if item_type == Comment:
            return distributions.CommentDownvoted
        elif item_type == Reply:
            return distributions.ReplyDownvoted
        elif item_type == Thread:
            return distributions.ThreadDownvoted
        else:
            raise error


@receiver(post_delete, sender=Distribution, dispatch_uid='delete_distribution')
def revoke_reputation(sender, instance, **kwargs):
    # TODO: Use F expression here to avoid race conditions
    recipient = instance.recipient
    amount = instance.amount
    current = recipient.reputation
    recipient.reputation = current - amount
    recipient.save(update_fields=['reputation'])


def is_eligible_for_new_user_bonus(user):
    return (
        (user.date_joined > new_user_cutoff_date())
        and (user.reputation < NEW_USER_BONUS_REPUTATION_LIMIT)
    )


def new_user_cutoff_date():
    return timezone.now() - timedelta(days=NEW_USER_BONUS_DAYS_LIMIT)
