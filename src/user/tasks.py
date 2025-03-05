from django.apps import apps
from django.core.cache import cache
from django_elasticsearch_dsl.registries import registry

from discussion.reaction_models import Vote as GrmVote
from paper.models import Paper
from researchhub.celery import QUEUE_ELASTIC_SEARCH, app
from researchhub.settings import APP_ENV
from user.editor_payout_tasks import editor_daily_payout_task
from user.rsc_exchange_rate_record_tasks import rsc_exchange_rate_record_tasks
from utils.sentry import log_info


@app.task
def handle_spam_user_task(user_id, requestor=None):
    User = apps.get_model("user.User")
    user = User.objects.filter(id=user_id).first()
    from researchhub_comment.views.rh_comment_view import remove_bounties

    if user:
        user.papers.update(is_removed=True)
        comments = user.created_researchhub_comment_rhcommentmodel.all()
        for comment in comments.iterator():
            remove_bounties(comment)
            if requestor:
                from discussion.reaction_views import censor

                censor(requestor, comment)
                comment.refresh_related_discussion_count()

        user.actions.update(display=False, is_removed=True)


@app.task
def reinstate_user_task(user_id):
    User = apps.get_model("user.User")
    ResearchhubUnifiedDocument = apps.get_model(
        "researchhub_document.ResearchhubUnifiedDocument"
    )
    user = User.objects.get(id=user_id)

    papers = Paper.objects.filter(uploaded_by=user)
    papers.update(is_removed=False)

    ResearchhubUnifiedDocument.all_objects.filter(paper__in=papers).update(
        is_removed=False
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

        if isinstance(item, GrmVote):
            if item.item.paper in papers:
                updates.append(action)
        else:
            if item.paper in papers:
                updates.append(action)
    return updates


@app.task(queue=QUEUE_ELASTIC_SEARCH)
def update_elastic_registry(user_id):
    Author = apps.get_model("user.Author")
    user_author = Author.objects.get(user_id=user_id)
    registry.update(user_author)


@app.task
def execute_editor_daily_payout_task():
    log_info(f"{APP_ENV}-running payout")
    result = editor_daily_payout_task()
    log_info(f"{APP_ENV}-running payout result: {str(result)}")
    return result


@app.task
def execute_rsc_exchange_rate_record_tasks():
    log_info(f"{APP_ENV}-running rsc_exchange_rate_record_tasks")
    result = rsc_exchange_rate_record_tasks()
    log_info(f"{APP_ENV}-running rsc_exchange_rate_record_tasks result: {str(result)}")


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
