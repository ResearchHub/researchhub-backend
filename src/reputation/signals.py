from datetime import timedelta
import json
import logging
from time import time

from django.db.models.signals import m2m_changed, post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.contrib.admin.options import get_content_type_for_model

from bullet_point.models import (
    BulletPoint,
    Endorsement as BulletPointEndorsement,
    Flag as BulletPointFlag
)
from discussion.models import (
    Comment,
    Endorsement as DiscussionEndorsement,
    Flag as DiscussionFlag,
    Reply,
    Thread,
    Vote as DiscussionVote
)
import ethereum.lib
from paper.models import (
    Flag as PaperFlag,
    Paper,
    Vote as PaperVote
)
from researchhub.settings import ASYNC_SERVICE_HOST
from reputation.distributor import Distributor
import reputation.distributions as distributions
from reputation.exceptions import ReputationSignalError
from reputation.models import Distribution, Withdrawal
from summary.models import Summary
from user.models import User
from utils.http import http_request, RequestMethods
from utils import sentry

# TODO: "Suspend" user if their reputation becomes negative
# This could mean setting `is_active` to false

ELIGIBLE_PAPER_FLAG_COUNT = 3
NEW_USER_BONUS_REPUTATION_LIMIT = 200
NEW_USER_BONUS_DAYS_LIMIT = 30


@receiver(post_save, sender=User, dispatch_uid='sign_up')
def distribute_for_sign_up(sender, instance, created, **kwargs):
    timestamp = time()
    if created and is_eligible_user(instance):
        distributor = Distributor(
            distributions.SignUp,
            instance,
            instance,
            timestamp
        )
        distributor.distribute()


@receiver(post_save, sender=Paper, dispatch_uid='create_paper')
def distribute_for_create_paper(sender, instance, created, **kwargs):
    timestamp = time()
    if created and is_eligible_user(instance.uploaded_by):
        distributor = Distributor(
            distributions.CreatePaper,
            instance.uploaded_by,
            instance,
            timestamp,
        )
        distributor.distribute()


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


@receiver(
    m2m_changed,
    sender=Paper.authors.through,
    dispatch_uid='create_authored_paper'
)
def distribute_for_create_authored_paper(
    sender,
    instance,
    action,
    reverse,
    model,
    pk_set,
    **kwargs
):
    timestamp = time()
    if (action == "post_add") and pk_set is not None:
        if check_uploaded_by_author(instance, pk_set):
            distributor = Distributor(
                distributions.CreateAuthoredPaper,
                instance.uploaded_by,
                instance,
                timestamp,
                instance.hubs.all()
            )
            distributor.distribute()


def check_uploaded_by_author(paper, pk_set):
    return (
        is_eligible_author(paper.uploaded_by)
        and (paper.uploaded_by.author_profile.id in pk_set)
    )


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
    paper_uploader = instance.paper.uploaded_by

    if created and is_eligible_for_vote_on_paper(recipient, paper_uploader):
        distributor = Distributor(
            distributions.VoteOnPaper,
            recipient,
            instance,
            timestamp,
            instance.paper.hubs.all(),
        )
        distributor.distribute()


def is_eligible_for_vote_on_paper(user, paper_uploader):
    return (
        is_eligible_user(user)
        and (user != paper_uploader)
        and is_eligible_for_new_user_bonus(user)
    )


@receiver(post_save, sender=PaperFlag, dispatch_uid='flag_paper')
def distribute_for_flag_paper(
    sender,
    instance,
    created,
    **kwargs
):
    timestamp = time()
    if created:
        recipients = get_eligible_paper_flaggers(instance.paper)
        if len(recipients) == ELIGIBLE_PAPER_FLAG_COUNT:
            for recipient in recipients:
                if is_eligible_user(recipient):
                    distributor = Distributor(
                        distributions.FlagPaper,
                        recipient,
                        instance,
                        timestamp,
                        instance.paper.hubs.all(),
                    )
                    distributor.distribute()


def get_eligible_paper_flaggers(paper):
    flaggers = []
    flags = paper.flags.all()
    if len(flags) == ELIGIBLE_PAPER_FLAG_COUNT:
        flags = flags[:ELIGIBLE_PAPER_FLAG_COUNT]
        for flag in flags:
            flaggers.append(flag.created_by)
    return flaggers


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

    if created and is_eligible_for_create_summary(recipient):
        distribution = distributions.CreateSummary
    elif (
        not created
        and check_approved_updated(update_fields)
        and instance.is_first_paper_summary
    ):
        distribution = distributions.CreateFirstSummary
    else:
        return

    distributor = Distributor(
        distribution,
        recipient,
        instance,
        timestamp,
        instance.paper.hubs.all(),
    )
    distributor.distribute()


def is_eligible_for_create_summary(user):
    return is_eligible_user(user) and is_eligible_for_new_user_bonus(user)


def check_approved_updated(update_fields):
    if update_fields is not None:
        return 'approved' in update_fields
    return False


@receiver(post_save, sender=BulletPoint, dispatch_uid='create_bullet_point')
@receiver(post_save, sender=Comment, dispatch_uid='create_comment')
@receiver(post_save, sender=Reply, dispatch_uid='create_reply')
@receiver(post_save, sender=Thread, dispatch_uid='create_thread')
def distribute_for_create_discussion(sender, instance, created, **kwargs):
    timestamp = time()
    recipient = instance.created_by
    hubs = None
    if created and is_eligible_for_create_discussion(recipient):
        if isinstance(instance, BulletPoint):
            distribution = distributions.CreateBulletPoint
            hubs = instance.paper.hubs
        elif isinstance(instance, Comment):
            distribution = distributions.CreateComment
            hubs = instance.parent.paper.hubs
        elif isinstance(instance, Reply):
            try:
                hubs = instance.parent.parent.paper.hubs
            except Exception as e:
                sentry.log_error(e)

            distribution = distributions.CreateReply
            if check_author_replied_to_user_comment(instance):
                distribution = distributions.CreateReplyAsAuthor
        elif isinstance(instance, Thread):
            distribution = distributions.CreateThread
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
        distributor.distribute()


def is_eligible_for_create_discussion(user):
    return is_eligible_user(user) and is_eligible_for_new_user_bonus(user)


def check_author_replied_to_user_comment(reply):
    if isinstance(reply.parent, Comment):
        return (
            check_reply_created_by_reply_paper_author(reply)
            and check_reply_to_other_creator(reply)
        )
    else:
        return False


def check_reply_to_other_creator(reply):
    return reply.parent.created_by is not reply.created_by


@receiver(post_save, sender=BulletPointFlag, dispatch_uid='bullet_point_flag')
@receiver(
    post_save,
    sender=BulletPointEndorsement,
    dispatch_uid='bullet_point_endorsement'
)
@receiver(post_save, sender=DiscussionFlag, dispatch_uid='discussion_flag')
@receiver(
    post_save,
    sender=DiscussionEndorsement,
    dispatch_uid='discussion_endorsement'
)
def distribute_for_action(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    timestamp = time()
    distributor = None
    hubs = None

    if created:
        try:
            if isinstance(instance, BulletPointFlag):
                distribution = distributions.BulletPointFlagged
                recipient = instance.bullet_point.created_by
                hubs = instance.bullet_point.paper.hubs

            elif isinstance(instance, BulletPointEndorsement):
                distribution = distributions.BulletPointEndorsed
                recipient = instance.bullet_point.created_by
                hubs = instance.bullet_point.paper.hubs

            if isinstance(instance, DiscussionFlag):
                distribution = get_discussion_flag_item_distribution(instance)
                recipient = instance.item.created_by

                if isinstance(instance.item, BulletPoint):
                    hubs = instance.item.paper.hubs
                elif isinstance(instance.item, Comment):
                    hubs = instance.item.parent.paper.hubs
                elif isinstance(instance.item, Reply):
                    try:
                        hubs = instance.item.parent.parent.paper.hubs
                    except Exception as e:
                        sentry.log_error(e)
                elif isinstance(instance.item, Thread):
                    hubs = instance.item.paper.hubs

            elif isinstance(instance, DiscussionEndorsement):
                distribution = get_discussion_endorsement_item_distribution(
                    instance
                )
                recipient = instance.item.created_by

                if isinstance(instance.item, BulletPoint):
                    hubs = instance.item.paper.hubs
                elif isinstance(instance.item, Comment):
                    hubs = instance.item.parent.paper.hubs
                elif isinstance(instance.item, Reply):
                    try:
                        hubs = instance.item.parent.parent.paper.hubs
                    except Exception as e:
                        sentry.log_error(e)
                elif isinstance(instance.item, Thread):
                    hubs = instance.item.paper.hubs

            else:
                raise TypeError

            if is_eligible_user(recipient):
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
                'Failed to distribute'
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
    try:
        recipient = instance.item.created_by
    except Exception as e:
        error = ReputationSignalError(e, 'Invalid recipient')
        print(error)
        return

    if (created or vote_type_updated(update_fields)) and is_eligible_user(
        recipient
    ):
        hubs = None
        if isinstance(instance.item, BulletPoint):
            hubs = instance.item.paper.hubs
        elif isinstance(instance.item, Comment):
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
        if isinstance(instance.item, BulletPoint):
            hubs = instance.item.paper.hubs
        elif isinstance(instance.item, Comment):
            hubs = instance.item.parent.paper.hubs
        elif isinstance(instance.item, Reply):
            try:
                hubs = instance.item.parent.parent.paper.hubs
            except Exception as e:
                sentry.log_error(e)
        elif isinstance(instance.item, Thread):
            hubs = instance.item.paper.hubs

        try:
            distribution = get_vote_on_discussion_item_distribution(
                instance
            )
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
                'Failed to distribute for vote on discussion'
            )
            print(error)

    if distributor is not None:
        distributor.distribute()


def is_eligible_for_vote_on_discussion(user):
    return is_eligible_user(user) and is_eligible_for_new_user_bonus(user)


def is_eligible_author(user):
    if user is not None:
        return user.is_active and (user.author_profile.orcid_id is not None)
    return False


def is_eligible_user(user):
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
    item = instance.item
    item_type = type(item)

    error = TypeError(f'Instance of type {item_type} is not supported')

    if vote_type == DiscussionVote.UPVOTE:
        if item_type == Comment:
            if check_comment_created_by_comment_paper_author(item):
                return distributions.AuthorCommentUpvoted
            return distributions.CommentUpvoted
        elif item_type == Reply:
            if check_reply_created_by_reply_paper_author(item):
                return distributions.AuthorReplyUpvoted
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


def check_comment_created_by_comment_paper_author(comment):
    return (
        is_eligible_author(comment.created_by)
        and (comment.created_by.author_profile in comment.paper.authors.all())
    )


def check_reply_created_by_reply_paper_author(reply):
    return (
        is_eligible_author(reply.created_by)
        and (reply.created_by.author_profile in reply.paper.authors.all())
    )


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
    # TODO: Use F expression here to avoid race conditions
    recipient = instance.recipient
    amount = instance.amount
    current = recipient.reputation
    recipient.reputation = current - amount
    recipient.save(update_fields=['reputation'])


@receiver(post_save, sender=Withdrawal, dispatch_uid='withdrawal')
def pay_withdrawal(sender, instance, created, **kwargs):
    if not created:
        return

    withdrawal = instance
    try:
        pending_withdrawal = PendingWithdrawal(withdrawal)
        pending_withdrawal.complete_token_transfer()
    except Exception as e:
        withdrawal.set_paid_failed()
        error = ReputationSignalError(
            e,
            f'Failed to pay withdrawal {withdrawal.id}'
        )
        logging.error(error)
        sentry.log_error(error, error.message)
        return


def is_eligible_for_new_user_bonus(user):
    return (
        (user.date_joined > new_user_cutoff_date())
        and (user.reputation < NEW_USER_BONUS_REPUTATION_LIMIT)
    )


def new_user_cutoff_date():
    return timezone.now() - timedelta(days=NEW_USER_BONUS_DAYS_LIMIT)


class PendingWithdrawal:
    def __init__(self, withdrawal):
        self.withdrawal = withdrawal

    def complete_token_transfer(self):
        self.balance_payout = self.withdrawal.user.get_balance()
        if self.balance_payout <= 0:
            # TODO: Change this to PendingWithdrawalError
            raise ReputationSignalError(
                None,
                'Insufficient balance to pay out'
            )
        self.withdrawal.set_paid_pending()
        self.token_payout = self._calculate_tokens_and_update_withdrawal_amount()  # noqa
        token_contract = ethereum.contracts.research_coin_contract
        transaction_hash = ethereum.utils.execute_erc20_transfer(
            token_contract,
            self.withdrawal.to_address,
            self.token_payout
        )
        self.withdrawal.transaction_hash = transaction_hash
        self.withdrawal.save()
        self._track_withdrawal_paid_status()

    def _calculate_tokens_and_update_withdrawal_amount(self):
        token_payout, withdrawal_amount = ethereum.lib.convert_reputation_amount_to_token_amount(  # noqa: E501
            'rhc',
            self.balance_payout
        )
        self.withdrawal.amount = withdrawal_amount
        self.withdrawal.save()
        return token_payout

    def _track_withdrawal_paid_status(self):
        url = ASYNC_SERVICE_HOST + '/ethereum/track_withdrawal'
        data = {
            'withdrawal': self.withdrawal.id,
            'transaction_hash': self.withdrawal.transaction_hash
        }
        response = http_request(
            RequestMethods.POST,
            url,
            data=json.dumps(data),
            timeout=3
        )
        logging.error(response.content)
        return response
