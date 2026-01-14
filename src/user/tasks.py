import logging

from django.apps import apps
from django.core.cache import cache

from discussion.models import Vote
from paper.models import Paper
from researchhub.celery import app
from user.editor_payout_tasks import editor_daily_payout_task
from user.rsc_exchange_rate_record_tasks import rsc_exchange_rate_record_tasks

logger = logging.getLogger(__name__)


@app.task
def handle_spam_user_task(user_id, requestor=None):
    from researchhub_document.models import ResearchhubUnifiedDocument
    from user.models import User

    user = User.objects.filter(id=user_id).first()
    from researchhub_comment.views.rh_comment_view import remove_bounties

    if user:
        papers = user.papers.all()
        papers.update(is_removed=True)
        ResearchhubUnifiedDocument.all_objects.filter(paper__in=papers).update(
            is_removed=True
        )

        posts = user.created_posts.all()
        post_unified_docs = ResearchhubUnifiedDocument.all_objects.filter(
            posts__in=posts
        ).distinct()
        post_unified_docs.update(is_removed=True)

        comments = user.created_researchhub_comment_rhcommentmodel.all()
        for comment in comments.iterator():
            remove_bounties(comment)
            if requestor:
                from discussion.views import censor

                censor(comment)
                comment.refresh_related_discussion_count()

        user.actions.update(display=False, is_removed=True)


@app.task
def reinstate_user_task(user_id):
    from researchhub_comment.models import RhCommentModel
    from researchhub_document.models import ResearchhubUnifiedDocument
    from user.models import User

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
