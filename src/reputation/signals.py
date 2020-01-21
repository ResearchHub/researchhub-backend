from datetime import timedelta
from time import time

from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone

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
import reputation.distributions as distributions
from reputation.exceptions import ReputationSignalError
from reputation.lib import get_unpaid_distributions
from reputation.models import Distribution, Withdrawal
from reputation.utils import get_total_reputation_from_distributions
from summary.models import Summary
import utils.sentry as sentry

# TODO: "Suspend" user if their reputation becomes negative
# This could mean setting `is_active` to false


@receiver(post_save, sender=Paper, dispatch_uid='create_paper')
def distribute_for_create_paper(sender, instance, created, **kwargs):
    timestamp = time()
    if created and is_eligible(instance.uploaded_by):
        distributor = Distributor(
            distributions.CreatePaper,
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
    """Distributes reputation to the voter."""
    timestamp = time()
    recipient = instance.created_by

    if created and is_eligible_for_vote_on_paper(recipient):
        distributor = Distributor(
            distributions.VoteOnPaper,
            recipient,
            instance,
            timestamp
        )
        distributor.distribute()


def is_eligible_for_vote_on_paper(user):
    return is_eligible(user) and (
        (user.date_joined > seven_days_ago())
        and (user.reputation < 200)
    )


@receiver(post_save, sender=Summary, dispatch_uid='create_summary')
def distribute_for_create_summary(sender, instance, created, **kwargs):
    timestamp = time()
    recipient = instance.proposed_by
    if created and is_eligible_for_create_summary(recipient):
        distributor = Distributor(
            distributions.CreateSummary,
            recipient,
            instance,
            timestamp
        )
        distributor.distribute()


def is_eligible_for_create_summary(user):
    return is_eligible(user) and (
        (user.date_joined > seven_days_ago())
        and (user.reputation < 200)
    )


@receiver(post_save, sender=Comment, dispatch_uid='create_comment')
def distribute_for_create_comment(sender, instance, created, **kwargs):
    timestamp = time()
    recipient = instance.created_by
    if created and is_eligible_for_create_discussion(recipient):
        distributor = Distributor(
            distributions.CreateComment,
            recipient,
            instance,
            timestamp
        )
        distributor.distribute()


@receiver(post_save, sender=Reply, dispatch_uid='create_reply')
def distribute_for_create_reply(sender, instance, created, **kwargs):
    timestamp = time()
    recipient = instance.created_by
    if created and is_eligible_for_create_discussion(recipient):
        distributor = Distributor(
            distributions.CreateReply,
            recipient,
            instance,
            timestamp
        )
        distributor.distribute()


@receiver(post_save, sender=Thread, dispatch_uid='create_thread')
def distribute_for_create_thread(sender, instance, created, **kwargs):
    timestamp = time()
    recipient = instance.created_by
    if created and is_eligible_for_create_discussion(recipient):
        distributor = Distributor(
            distributions.CreateThread,
            recipient,
            instance,
            timestamp
        )
        distributor.distribute()


def is_eligible_for_create_discussion(user):
    return is_eligible(user) and (
        (user.date_joined > seven_days_ago())
        and (user.reputation < 200)
    )


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
    """Distributes reputation to the creator of the item voted on."""
    timestamp = time()
    distributor = None
    recipient = instance.item.created_by

    if (created or vote_type_updated(update_fields)) and is_eligible(
        recipient
    ):
        # TODO: This needs to be altered so that if the vote changes the
        # original distribution is deleted if not yet withdrawn
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
                'Failed to distribute for discussion vote'
            )
            print(error)

    if distributor is not None:
        distributor.distribute()


@receiver(post_save, sender=DiscussionVote, dispatch_uid='vote_on_discussion')
def distribute_for_vote_on_discussion(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    """Distributes reputation to the voter."""
    timestamp = time()
    distributor = None
    recipient = instance.created_by

    if created and is_eligible_for_vote_on_discussion(recipient):
        try:
            distribution = get_vote_on_discussion_item_distribution(
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
                'Failed to distribute for vote on discussion'
            )
            print(error)

    if distributor is not None:
        distributor.distribute()


def is_eligible_for_vote_on_discussion(user):
    return is_eligible(user) and user.date_joined > seven_days_ago()


def is_eligible(user):
    if user is not None:
        return user.is_active
    return False


def seven_days_ago():
    return timezone.now() - timedelta(days=7)


def vote_type_updated(update_fields):
    if update_fields is not None:
        return 'vote_type' in update_fields
    return False


def get_discussion_endorsement_item_distribution(instance):
    item_type = type(instance.item)

    error = TypeError(f'Instance of type {item_type} is not supported')

    if item_type == Comment:
        return distributions.CommentEndorsed
    elif item_type == Reply:
        return distributions.ReplyEndorsed
    elif item_type == Thread:
        return distributions.ThreadEndorsed
    else:
        raise error


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
    item_type = type(instance.item)

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


def get_vote_on_discussion_item_distribution(instance):
    item_type = type(instance.item)

    error = TypeError(f'Instance of type {item_type} is not supported')

    if item_type == Comment:
        return distributions.VoteOnComment
    elif item_type == Reply:
        return distributions.VoteOnReply
    elif item_type == Thread:
        return distributions.VoteOnThread
    else:
        raise error


@receiver(post_delete, sender=Distribution, dispatch_uid='delete_distribution')
def revoke_reputation(sender, instance, **kwargs):
    recipient = instance.recipient
    amount = instance.amount
    current = recipient.reputation
    recipient.reputation = current - amount
    recipient.save(update_fields=['reputation'])


@receiver(post_save, sender=Withdrawal, dispatch_uid='withdrawal')
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
