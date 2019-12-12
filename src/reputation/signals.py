from time import time

from django.db import transaction, IntegrityError
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
from paper.models import (
    Paper,
    Vote as PaperVote
)
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
    ThreadDownvoted,
    VoteOnPaper,
)
from reputation.exceptions import ReputationSignalError
from reputation.lib import get_unpaid_distributions
from reputation.models import Withdrawal
from reputation.utils import get_total_reputation_from_distributions
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


@receiver(post_save, sender=PaperVote, dispatch_uid='vote_on_paper')
def distribute_for_vote_on_paper(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    timestamp = time()
    distributor = None
    recipient = instance.created_by

    if created and is_eligible(recipient) and (
        recipient.first_vote_on_paper_distribution is None
    ):
        try:
            distribution = VoteOnPaper
            distributor = Distributor(
                distribution,
                recipient,
                instance,
                timestamp
            )
            with transaction.atomic():
                record = distributor.distribute()
                recipient.refresh_from_db()
                recipient.set_first_vote_on_paper_distribution(record)
        except IntegrityError as e:
            error = ReputationSignalError(
                e,
                'Failed to distribute for vote on paper'
            )
            print(error)


@receiver(post_save, sender=Endorsement, dispatch_uid='discussion_endorsement')
def distribute_for_discussion_endorsement(
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
            distribution = get_discussion_endorsement_item_distribution(
                instance
            )
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
def distribute_for_discussion_flag(
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
            distribution = get_discussion_flag_item_distribution(instance)
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
def distribute_for_discussion_vote(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    timestamp = time()
    distributor = None
    recipient = instance.item.created_by

    if (created or vote_type_updated(update_fields)) and is_eligible(
        recipient
    ):
        try:
            distribution = get_discussion_vote_item_distribution(instance)
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


def vote_type_updated(update_fields):
    if update_fields is not None:
        return 'vote_type' in update_fields
    return False


def get_discussion_endorsement_item_distribution(instance):
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


def get_discussion_flag_item_distribution(instance):
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


def get_discussion_vote_item_distribution(instance):
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

    withdrawal_instance = instance
    withdrawal_for_update = Withdrawal.objects.filter(
        pk=instance.id
    ).select_for_update(of=('self',))
    try:
        with transaction.atomic():
            withdrawal = withdrawal_for_update.get()

            # only getting distributions with paid status None
            unpaid_distributions = get_unpaid_distributions(
                withdrawal.user
            ).select_for_update(of=('self',))

            eligible_distributions = add_withdrawal_to_distributions(
                unpaid_distributions,
                withdrawal
            )

            reputation_payout = get_reputation_payout(
                eligible_distributions
            )

            token_payout, withdrawal_amount = ethereum.lib.convert_reputation_amount_to_token_amount(  # noqa: E501
                'rhc',
                reputation_payout
            )

            # TODO: Clean this up a bit
            withdrawal.amount = withdrawal_amount
            withdrawal.save()

            # TODO: Replace paid updates this with a call to our async service
            for ed in eligible_distributions:
                ed.set_paid()
            withdrawal.set_paid()

            complete_withdrawal_transfer(
                token_payout,
                withdrawal
            )

    except Exception as e:
        withdrawal_instance.set_paid_failed()
        error = ReputationSignalError(
            e,
            f'Failed to pay withdrawal {withdrawal.id}'
        )
        sentry.log_error(error, error.message)
        print(error)
        return


def add_withdrawal_to_distributions(distributions, withdrawal):
    updated_distributions = []
    for d in distributions:
        try:
            with transaction.atomic():
                d.set_paid_pending()
                d.set_withdrawal(withdrawal)
                updated_distributions.append(d)
        except Exception:
            pass
    return updated_distributions


def get_reputation_payout(distributions):
    reputation_payout = get_total_reputation_from_distributions(
        distributions
    )
    if reputation_payout <= 0:
        raise ReputationSignalError(
            None,
            'Insufficient balance to pay out'
        )
    return reputation_payout


def complete_withdrawal_transfer(amount, withdrawal):
    token_contract = ethereum.contracts.research_coin_contract
    transaction_hash = ethereum.utils.execute_erc20_transfer(
        token_contract,
        withdrawal.to_address,
        amount
    )
    withdrawal.transaction_hash = transaction_hash
    withdrawal.save()
