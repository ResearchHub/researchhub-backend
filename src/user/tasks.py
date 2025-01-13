from django.apps import apps
from django.core.cache import cache
from django.http.request import HttpRequest
from django_elasticsearch_dsl.registries import registry
from rest_framework.request import Request

from discussion.lib import (
    check_comment_in_threads,
    check_reply_in_comments,
    check_reply_in_threads,
    check_thread_in_papers,
)
from discussion.models import Comment, Reply, Thread
from discussion.models import Vote as GrmVote
from paper.models import Paper
from paper.utils import get_cache_key
from researchhub.celery import QUEUE_CACHES, QUEUE_ELASTIC_SEARCH, app
from researchhub.settings import APP_ENV, PRODUCTION, STAGING
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


def get_my_updates(user, actions):
    updates = []
    my_papers = user.author_profile.papers.all()
    my_threads = Thread.objects.filter(created_by=user)
    my_comments = Comment.objects.filter(created_by=user)

    # TODO: Change this to a "subscribed to comment" model

    for action in actions:
        item = action.item

        if isinstance(item, Comment):
            # is it a comment on my thread?
            if check_comment_in_threads(item, my_threads):
                updates.append(action)
            # is it a comment on my paper?
            # TODO

        elif isinstance(item, Reply):
            # is it a reply on my thread?
            if check_reply_in_threads(item, my_threads):
                updates.append(action)
            # is it a reply on my comment?
            if check_reply_in_comments(item, my_comments):
                updates.append(action)
            # is it a reply on my reply?

        elif isinstance(item, Thread):
            # is it a thread on my paper?
            if check_thread_in_papers(item, my_papers):
                updates.append(action)


def filter_comments_on_my_threads(comments, threads):
    return [comment for comment in comments if comment.parent in threads]


@app.task(queue=QUEUE_CACHES)
def preload_latest_activity(hub_ids, ordering):
    from reputation.serializers import DynamicContributionSerializer
    from user.views import UserViewSet

    hub_ids_str = hub_ids
    request_path = "/api/user/following_latest_activity/"
    if STAGING:
        http_host = "backend.staging.researchhub.com"
        protocol = "https"
    elif PRODUCTION:
        http_host = "backend.prod.researchhub.com"
        protocol = "https"
    else:
        http_host = "localhost:8000"
        protocol = "http"

    query_string = f"?page=1&hub_ids={hub_ids_str}"
    http_meta = {
        "QUERY_STRING": query_string,
        "HTTP_HOST": http_host,
        "HTTP_X_FORWARDED_PROTO": protocol,
    }

    cache_key = get_cache_key("contributions", hub_ids_str)
    user_view = UserViewSet()
    http_req = HttpRequest()
    http_req.META = http_meta
    http_req.path = request_path
    req = Request(http_req)
    user_view.request = req

    latest_activities = user_view._get_latest_activity_queryset(hub_ids_str, ordering)
    page = user_view.paginate_queryset(latest_activities)
    context = user_view._get_latest_activity_context()
    serializer = DynamicContributionSerializer(
        page,
        _include_fields=[
            "contribution_type",
            "created_date",
            "id",
            "source",
            "unified_document",
            "user",
        ],
        context=context,
        many=True,
    )
    serializer_data = serializer.data

    paginated_response = user_view.get_paginated_response(serializer_data)

    cache.set(cache_key, paginated_response.data, timeout=60 * 60 * 24)

    return paginated_response.data


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
