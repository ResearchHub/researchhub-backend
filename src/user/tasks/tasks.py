import logging

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from discussion.constants.flag_reasons import NOT_SPECIFIED
from discussion.models import Flag, Vote
from discussion.views import censor
from feed.models import FeedEntry
from notification.models import Notification
from paper.models import Paper
from purchase.models import Fundraise, Grant
from purchase.services.fundraise_service import FundraiseService
from reputation.models import Bounty
from researchhub.celery import app
from researchhub_comment.models import RhCommentModel
from researchhub_comment.views.rh_comment_view import remove_bounties
from researchhub_document.models import ResearchhubUnifiedDocument
from review.models.peer_review_model import PeerReview
from review.models.review_model import Review
from user.editor_payout_tasks import editor_daily_payout_task
from user.models import User
from user.related_models.verdict_model import Verdict
from user.rsc_exchange_rate_record_tasks import rsc_exchange_rate_record_tasks

logger = logging.getLogger(__name__)


@app.task
def handle_spam_user_task(user_id, requestor=None):
    user = User.objects.filter(id=user_id).first()
    if not user:
        return

    logger.info(f"Removing content of spam user={user_id}")

    # Censor comments and cancel any bounties attached to them
    comments = user.created_researchhub_comment_rhcommentmodel.all()
    for comment in comments.iterator():
        remove_bounties(comment)
        if requestor:
            censor(comment)
            comment.refresh_related_discussion_count()

    # Remove papers and their unified documents
    papers = user.papers.all()
    papers.update(is_removed=True)
    ResearchhubUnifiedDocument.all_objects.filter(paper__in=papers).update(
        is_removed=True
    )

    # Remove posts (discussions, questions, preregistrations, grants, etc.)
    posts = user.created_posts.all()
    post_unified_docs = ResearchhubUnifiedDocument.all_objects.filter(
        posts__in=posts
    ).distinct()
    post_unified_docs.update(is_removed=True)

    # Hide all activity feed actions
    user.actions.update(display=False, is_removed=True)

    # Remove notes
    ResearchhubUnifiedDocument.all_objects.filter(note__created_by=user).update(
        is_removed=True
    )

    # Cancel any remaining open bounties the user created on other users' content
    for bounty in user.bounties.filter(status__in=[Bounty.OPEN, Bounty.ASSESSMENT]):
        bounty.close(Bounty.CANCELLED)

    # Soft-delete peer reviews and reviews
    now = timezone.now()
    PeerReview.objects.filter(user=user).update(
        is_removed=True, is_public=False, is_removed_date=now
    )
    Review.objects.filter(created_by=user).update(
        is_removed=True, is_public=False, is_removed_date=now
    )

    # Close open fundraises and refund escrowed RSC to contributors
    fundraise_service = FundraiseService()
    for fundraise in user.fundraises.filter(status=Fundraise.OPEN).select_related(
        "escrow"
    ):
        fundraise_service.close_fundraise(fundraise)

    # Close open grants (RFPs)
    user.grants.filter(status=Grant.OPEN).update(status=Grant.CLOSED)

    # Purge feed entries and notifications
    FeedEntry.objects.filter(user=user).delete()
    Notification.objects.filter(action_user=user).delete()

    # Resolve any open moderation flags on the user's content
    _resolve_open_flags_for_user(user, requestor)


def _resolve_open_flags_for_user(user, requestor=None):
    """Create verdicts for all open flags on the user's content."""
    comment_ct = ContentType.objects.get(model="rhcommentmodel")
    post_ct = ContentType.objects.get(model="researchhubpost")
    paper_ct = ContentType.objects.get(model="paper")

    open_flags = Flag.objects.filter(verdict__isnull=True).filter(
        Q(
            content_type=comment_ct,
            object_id__in=RhCommentModel.all_objects.filter(
                created_by=user
            ).values_list("id", flat=True),
        )
        | Q(
            content_type=post_ct,
            object_id__in=user.created_posts.values_list("id", flat=True),
        )
        | Q(
            content_type=paper_ct,
            object_id__in=user.papers.values_list("id", flat=True),
        )
    )

    flags = list(open_flags)
    if not flags:
        return

    if requestor is None:
        requestor = User.objects.get_community_account()

    Flag.objects.filter(id__in=[f.id for f in flags]).update(
        verdict_created_date=timezone.now()
    )
    Verdict.objects.bulk_create(
        [
            Verdict(
                created_by=requestor,
                flag=flag,
                verdict_choice=flag.reason_choice or NOT_SPECIFIED,
                is_content_removed=True,
            )
            for flag in flags
        ]
    )


@app.task
def reinstate_user_task(user_id):
    user = User.objects.get(id=user_id)

    papers = Paper.objects.filter(uploaded_by=user)
    papers.update(is_removed=False)

    ResearchhubUnifiedDocument.all_objects.filter(paper__in=papers).update(
        is_removed=False
    )

    posts = user.created_posts.all()
    post_unified_docs = ResearchhubUnifiedDocument.all_objects.filter(
        posts__in=posts
    ).distinct()
    post_unified_docs.update(is_removed=False)

    # Restore comments
    RhCommentModel.all_objects.filter(created_by=user).update(
        is_removed=False, is_public=True, is_removed_date=None
    )

    # Restore actions
    user.actions.update(display=True, is_removed=False)

    # Restore notes
    ResearchhubUnifiedDocument.all_objects.filter(note__created_by=user).update(
        is_removed=False
    )

    # Restore peer reviews and reviews
    PeerReview.all_objects.filter(user=user).update(
        is_removed=False, is_public=True, is_removed_date=None
    )
    Review.all_objects.filter(created_by=user).update(
        is_removed=False, is_public=True, is_removed_date=None
    )


def get_latest_actions(cursor):
    Action = apps.get_model("user.Action")
    actions = Action.objects.all().order_by("-id")[cursor:]
    next_cursor = cursor + len(actions)
    return actions, next_cursor


def get_authored_paper_updates(author, latest_actions):
    updates = []
    papers = author.papers.all()
    for action in latest_actions:
        item = action.item

        if isinstance(item, Vote):
            if item.item.paper in papers:
                updates.append(action)
        else:
            if item.paper in papers:
                updates.append(action)
    return updates


@app.task
def execute_editor_daily_payout_task():
    result = editor_daily_payout_task()
    logger.info(f"Completed editor_daily_payout_task with result: {str(result)}")
    return result


@app.task
def execute_rsc_exchange_rate_record_tasks():
    result = rsc_exchange_rate_record_tasks()
    logger.info(f"Completed rsc_exchange_rate_record_tasks with result: {str(result)}")


@app.task
def invalidate_author_profile_caches(_ignore, author_id):
    """
    Invalidates all caches related to an author profile.
    This task is designed to be called from a chain when other tasks complete.
    Celery requires the first argument to be the result of the previous task.
    It is ignored in this case.
    """
    cache.delete(f"author-{author_id}-achievements")
    cache.delete(f"author-{author_id}-overview")
    cache.delete(f"author-{author_id}-profile")
    cache.delete(f"author-{author_id}-publications")
    cache.delete(f"author-{author_id}-summary-stats")
