from time import time

from django.db.models.signals import post_save
from django.dispatch import receiver

from .distributor import Distributor
from .distributions import (
    CommentEndorsed,
    CommentFlagged,
    CommentUpvoted,
    CommentDownvoted,
    CreatePaper,
    ReplyEndorsed,
    ReplyFlagged,
    ReplyUpvoted,
    ReplyDownvoted,
    ThreadEndorsed,
    ThreadFlagged,
    ThreadUpvoted,
    ThreadDownvoted
)

from discussion.models import (
    Comment,
    Endorsement,
    Flag as DiscussionFlag,
    Reply,
    Thread,
    Vote as DiscussionVote
)
from paper.models import Paper

# TODO: "Suspend" user if their reputation becomes negative
# This could mean setting `is_active` to false


@receiver(post_save, sender=Paper, dispatch_uid='create_paper')
def distribute_for_create_paper(sender, instance, created, **kwargs):
    timestamp = time()
    if created and is_eligible(instance.uploaded_by):
        distributor = Distributor(
            CreatePaper,
            instance.uploaded_by,
            instance,
            timestamp
        )
        distributor.distribute()


@receiver(post_save, sender=Endorsement, dispatch_uid='discussion_endorsement')
def distribute_for_endorsement(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    timestamp = time()
    distributor = None
    recipient = instance.item.created_by

    if created and is_eligible(recipient):
        try:
            distribution = get_endorsement_item_distribution(instance)
            distributor = Distributor(
                distribution,
                recipient,
                instance,
                timestamp
            )
        except TypeError as e:
            print(e)

    if distributor is not None:
        distributor.distribute()


@receiver(post_save, sender=DiscussionFlag, dispatch_uid='discussion_flag')
def distribute_for_flag(sender, instance, created, update_fields, **kwargs):
    timestamp = time()
    distributor = None
    recipient = instance.item.created_by

    if created and is_eligible(recipient):
        try:
            distribution = get_flag_item_distribution(instance)
            distributor = Distributor(
                distribution,
                recipient,
                instance,
                timestamp
            )
        except TypeError as e:
            print(e)

    if distributor is not None:
        distributor.distribute()


@receiver(post_save, sender=DiscussionVote, dispatch_uid='discussion_vote')
def distribute_for_vote(sender, instance, created, update_fields, **kwargs):
    timestamp = time()
    distributor = None
    recipient = instance.item.created_by

    if (created or vote_type_updated(update_fields)) and is_eligible(
        recipient
    ):
        try:
            distribution = get_vote_item_distribution(instance)
            distributor = Distributor(
                distribution,
                recipient,
                instance,
                timestamp
            )
        except TypeError as e:
            print(e)

    if distributor is not None:
        distributor.distribute()


def is_eligible(user):
    if user is not None:
        return user.is_active
    return False


def get_endorsement_item_distribution(instance):
    item_type = type(instance.item)

    error = TypeError(f'Instance of type {item_type} is not supported')

    if item_type == Comment:
        return CommentEndorsed
    elif item_type == Reply:
        return ReplyEndorsed
    elif item_type == Thread:
        return ThreadEndorsed
    else:
        raise error


def get_flag_item_distribution(instance):
    item_type = type(instance.item)

    error = TypeError(f'Instance of type {item_type} is not supported')

    if item_type == Comment:
        return CommentFlagged
    elif item_type == Reply:
        return ReplyFlagged
    elif item_type == Thread:
        return ThreadFlagged
    else:
        raise error


def vote_type_updated(update_fields):
    if update_fields is not None:
        return 'vote_type' in update_fields
    return False


def get_vote_item_distribution(instance):
    vote_type = instance.vote_type
    item_type = type(instance.item)

    error = TypeError(f'Instance of type {item_type} is not supported')

    if vote_type == DiscussionVote.UPVOTE:
        if item_type == Comment:
            return CommentUpvoted
        elif item_type == Reply:
            return ReplyUpvoted
        elif item_type == Thread:
            return ThreadUpvoted
        else:
            raise error

    elif vote_type == DiscussionVote.DOWNVOTE:
        if item_type == Comment:
            return CommentDownvoted
        elif item_type == Reply:
            return ReplyDownvoted
        elif item_type == Thread:
            return ThreadDownvoted
        else:
            raise error
