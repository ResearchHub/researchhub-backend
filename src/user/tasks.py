import logging
from datetime import timedelta

from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from celery.decorators import periodic_task
from celery.task.schedules import crontab
from django.apps import apps
from django.core.cache import cache
from django.db.models import Count, F, Q
from django.http.request import HttpRequest
from django.utils import timezone
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
from hub.models import Hub
from paper.models import Paper
from paper.utils import get_cache_key
from reputation.models import Contribution
from researchhub.celery import (
    QUEUE_CACHES,
    QUEUE_ELASTIC_SEARCH,
    QUEUE_NOTIFICATION,
    QUEUE_PAPER_MISC,
    QUEUE_PURCHASES,
    app,
)
from researchhub.settings import APP_ENV, PRODUCTION, STAGING
from researchhub_document.utils import reset_unified_document_cache
from user.editor_payout_tasks import editor_daily_payout_task
from user.rsc_exchange_rate_record_tasks import (
    rsc_exchange_rate_record_tasks,
)
from utils.sentry import log_info


@app.task
def handle_spam_user_task(user_id):
    User = apps.get_model("user.User")
    user = User.objects.filter(id=user_id).first()
    if user:
        user.papers.update(is_removed=True)
        user.paper_votes.update(is_removed=True)

        hub_ids = list(
            Hub.objects.filter(papers__in=list(user.papers.values_list(flat=True)))
            .values_list(flat=True)
            .distinct()
        )

        # Update discussions
        for thr in Thread.objects.filter(created_by=user):
            thr.remove_nested()
            thr.update_discussion_count()

        for com in Comment.objects.filter(created_by=user):
            com.remove_nested()
            com.update_discussion_count()

        for rep in Reply.objects.filter(created_by=user):
            rep.remove_nested()
            rep.update_discussion_count()

    reset_unified_document_cache(hub_ids)


@app.task
def reinstate_user_task(user_id):
    User = apps.get_model("user.User")
    ResearchhubUnifiedDocument = apps.get_model(
        "researchhub_document.ResearchhubUnifiedDocument"
    )
    user = User.objects.get(id=user_id)

    papers = Paper.objects.filter(uploaded_by=user)
    papers.update(is_removed=False)
    user.paper_votes.update(is_removed=False)

    ResearchhubUnifiedDocument.objects.filter(paper__in=papers).update(is_removed=False)

    hub_ids = list(
        Hub.objects.filter(papers__in=list(user.papers.values_list(flat=True)))
        .values_list(flat=True)
        .distinct()
    )

    # Update discussions
    for thr in Thread.objects.filter(created_by=user):
        thr.update_discussion_count()
        thr.is_removed = False
        thr.save()

    for com in Comment.objects.filter(created_by=user):
        com.update_discussion_count()
        com.is_removed = False
        com.save()

    for rep in Reply.objects.filter(created_by=user):
        rep.update_discussion_count()
        rep.is_removed = False
        rep.save()

    reset_unified_document_cache(hub_ids, {}, None)


@app.task(queue=QUEUE_PAPER_MISC)
def link_author_to_papers(author_id, orcid_account_id):
    Author = apps.get_model("user.Author")
    try:
        author = Author.objects.get(pk=author_id)
        orcid_account = SocialAccount.objects.get(pk=orcid_account_id)
        works = get_orcid_works(orcid_account.extra_data)
        for work in works:
            paper = get_orcid_paper(work)
            if paper is not None:
                paper.authors.add(author)
                paper.save()
                print(
                    f"Added author {author.id}"
                    f" to paper {paper.id}"
                    f" on doi {paper.doi}"
                )
    except (Author.DoesNotExist, SocialAccount.DoesNotExist) as e:
        logging.warning(f"{e} for author {author_id} orcid account {orcid_account_id}")


@app.task(queue=QUEUE_PAPER_MISC)
def link_paper_to_authors(paper_id):
    try:
        paper = Paper.objects.get(pk=paper_id)
        orcid_accounts = SocialAccount.objects.filter(provider=OrcidProvider.id)
        for orcid_account in orcid_accounts:
            works = get_orcid_works(orcid_account.extra_data)
            if check_doi_in_works(paper.doi, works):
                paper.authors.add(orcid_account.user.author_profile)
                paper.save()
                print(
                    f"Added author {orcid_account.user.author_profile.id}"
                    f" to paper {paper.id}"
                    f" on doi {paper.doi}"
                )
    except (Paper.DoesNotExist, SocialAccount.DoesNotExist) as e:
        logging.warning(f"{e} for paper {paper_id}")


def get_orcid_works(data):
    try:
        return data["activities-summary"]["works"]["group"]
    except Exception as e:
        print(e)
    return []


def get_orcid_paper(work):
    doi = get_work_doi(work)
    if doi is not None:
        try:
            return Paper.objects.get(doi=doi)
        except Paper.DoesNotExist:
            return None
    return None


def check_doi_in_works(doi, works):
    for work in works:
        work_doi = get_work_doi(work)
        if doi == work_doi:
            return True
    return False


def get_work_doi(work):
    eids = work["external-ids"]["external-id"]
    for eid in eids:
        if eid["external-id-type"] == "doi":
            return eid["external-id-value"]
    return None


def get_latest_actions(cursor):
    Action = apps.get_model("user.Action")
    actions = Action.objects.all().order_by("-id")[cursor:]
    next_cursor = cursor + len(actions)
    return actions, next_cursor


def get_authored_paper_updates(author, latest_actions):
    updates = []
    papers = author.authored_papers.all()
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
    my_papers = user.author_profile.authored_papers.all()
    my_threads = Thread.objects.filter(created_by=user)
    my_comments = Comment.objects.filter(created_by=user)
    # my_replies = Reply.objects.filter(created_by=user)

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
        http_host = "staging-backend.researchhub.com"
        protocol = "https"
    elif PRODUCTION:
        http_host = "backend.researchhub.com"
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


# Runs every Monday at 6am
@periodic_task(
    run_every=crontab(hour=6, minute=0, day_of_week=1),
    priority=5,
    queue=QUEUE_NOTIFICATION,
)
def notify_editor_inactivity():
    User = apps.get_model("user.User")

    last_week = timezone.now() - timedelta(days=7)
    editors = User.objects.editors()
    inactive_contributors = editors.annotate(
        paper_count=Count(
            "id",
            filter=Q(
                contributions__contribution_type=Contribution.SUBMITTER,
                contributions__created_date__gte=last_week,
            ),
        ),
        comment_count=Count(
            "id",
            filter=Q(
                contributions__contribution_type=Contribution.COMMENTER,
                contributions__created_date__gte=last_week,
            ),
        ),
        total_contributions=F("paper_count") + F("comment_count"),
    ).filter(total_contributions__lt=3)

    logging = []
    for inactive_contributor in inactive_contributors.iterator():
        paper_count = inactive_contributor.paper_count
        comment_count = inactive_contributor.comment_count
        logging.append(
            (
                inactive_contributor.email,
                f"Paper count: {paper_count}",
                f"Comment count: {comment_count}",
            )
        )
        inactive_contributor.notify_inactivity(paper_count, comment_count)
    log_info(logging)


@periodic_task(
    run_every=crontab(hour=15, minute=0),  # 3:00 PM PST (pst is system time)
    priority=2,
    queue=QUEUE_PURCHASES,
)
def execute_editor_daily_payout_task():
    log_info(f"{APP_ENV}-running payout")
    result = editor_daily_payout_task()
    log_info(result)


@periodic_task(
    run_every=crontab(hour="*", minute=0),  # every hour
    priority=2,
    queue=QUEUE_PURCHASES,
)
def execute_rsc_exchange_rate_record_tasks():
    log_info(f"{APP_ENV}-running rsc_exchange_rate_record_tasks")
    result = rsc_exchange_rate_record_tasks()
    log_info(result)
