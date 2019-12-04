from time import time

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

import ethereum.lib
from discussion.models import (
    Comment,
    Endorsement,
    Flag as DiscussionFlag,
    Reply,
    Thread,
    Vote as DiscussionVote
)
from paper.models import Paper
from reputation.distributor import Distributor
from reputation.distributions import (
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
from reputation.lib import (
    get_unpaid_distributions,
    get_total_reputation_from_distributions
)
from reputation.models import Withdrawal
from reputation.exceptions import ReputationSignalError
import utils.sentry as sentry

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
            error = ReputationSignalError(
                e,
                'Failed to distribute for endorsement'
            )
            print(error)

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
            error = ReputationSignalError(
                e,
                'Failed to distribute for flag'
            )
            print(error)

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
            error = ReputationSignalError(
                e,
                'Failed to distribute for flag'
            )
            print(error)

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


@receiver(post_save, sender=Withdrawal, dispatch_uid='')
def pay_withdrawal(sender, instance, created, **kwargs):
    if not created:
        return

    withdrawal = instance
    withdrawal_for_update = Withdrawal.objects.filter(
        pk=instance.id
    ).select_for_update(of=('self',))

    unpaid_distributions = get_unpaid_distributions(
        withdrawal.user
    ).select_for_update(of=('self',))

    eligible_distributions = []
    for distribution in unpaid_distributions:
        distribution.set_paid_pending()
        distribution.set_withdrawal(withdrawal)
        eligible_distributions.append(distribution)

    reputation_payout = get_total_reputation_from_distributions(
        eligible_distributions
    )
    if reputation_payout <= 0:
        error = ReputationSignalError(
            None,
            'Insufficient balance to pay out'
        )
        sentry.log_info(error.message)
        print(error)
        return

    token_payout = ethereum.lib.convert_reputation_amount_to_token_amount(
        'rhc',
        reputation_payout
    )
    token_contract = ethereum.contracts.research_coin_contract

    try:
        with transaction.atomic():
            w = withdrawal_for_update.get()

            for d in eligible_distributions:
                d.set_paid()
            w.set_paid()

            transaction_hash = ethereum.utils.execute_erc20_transfer(
                token_contract,
                w.to_address,
                token_payout
            )
            w.transaction_hash = transaction_hash
            w.save()
    except Exception as e:
        withdrawal.set_paid_failed()
        error = ReputationSignalError(
            e,
            f'Failed to pay withdrawal {withdrawal.id}'
        )
        sentry.log_error(error, error.message)
        print(error)
        return
