from datetime import datetime, timedelta
from django_elasticsearch_dsl.registries import registry

from celery.decorators import periodic_task
from celery.task.schedules import crontab
from django.apps import apps
from django.http.request import HttpRequest
from django.core.cache import cache
from rest_framework.request import Request

from researchhub_document.related_models.constants.document_type import (
    ALL,
    DISCUSSION,
    ELN,
    PAPER,
    HYPOTHESIS,
    POSTS,
)
from paper.utils import get_cache_key
from researchhub.celery import app
from researchhub.settings import (
    APP_ENV,
    STAGING,
    PRODUCTION,
)
from django.contrib.contenttypes.models import ContentType
from utils import sentry


@app.task
def recalc_hot_score_task(
    instance_content_type_id,
    instance_id
):
    content_type = ContentType.objects.get(id=instance_content_type_id)
    model_name = content_type.model
    model_class = content_type.model_class()
    uni_doc = None

    try:
        if model_name in ['hypothesis', 'researchhubpost', 'paper']:
            uni_doc = model_class.objects.get(id=instance_id).unified_document
        elif model_name in ['thread', 'comment', 'reply']:
            thread = None
            if model_name == 'thread':
                thread = model_class.objects.get(id=instance_id)
            elif model_name == 'comment':
                comment = model_class.objects.get(id=instance_id)
                thread = comment.parent
            elif model_name == 'reply':
                reply = model_class.objects.get(id=instance_id)
                thread = reply.parent.parent

            if thread.paper:
                uni_doc = thread.paper.unified_document
            elif thread.hypothesis:
                uni_doc = thread.hypothesis.unified_document
            elif thread.post:
                uni_doc = thread.post.unified_document
        elif model_name == 'paper':
            uni_doc = model_class.objects.get(id=instance_id).unified_document

        uni_doc.calculate_hot_score_v2()
    except Exception as error:
        print('recalc_hot_score error', error)
        sentry.log_error(error)


@app.task
def preload_trending_documents(
    document_type,
    hub_id,
    filtering,
    time_scope,
):
    from researchhub_document.views import ResearchhubUnifiedDocumentViewSet
    from researchhub_document.serializers import (
      DynamicUnifiedDocumentSerializer
    )


    initial_date = datetime.now().replace(
        hour=7,
        minute=0,
        second=0,
        microsecond=0
    )
    end_date = datetime.now()
    if time_scope == 'all_time':
        cache_pk = f'{document_type}_{hub_id}_{filtering}_all_time'
        start_date = datetime(
            year=2018,
            month=12,
            day=31,
            hour=7
        )
    elif time_scope == 'year':
        cache_pk = f'{document_type}_{hub_id}_{filtering}_year'
        start_date = initial_date - timedelta(days=365)
    elif time_scope == 'month':
        cache_pk = f'{document_type}_{hub_id}_{filtering}_month'
        start_date = initial_date - timedelta(days=30)
    elif time_scope == 'week':
        cache_pk = f'{document_type}_{hub_id}_{filtering}_week'
        start_date = initial_date - timedelta(days=7)
    else:
        start_date = datetime.now().replace(
            hour=7,
            minute=0,
            second=0,
            microsecond=0
        )
        cache_pk = f'{document_type}_{hub_id}_{filtering}_today'

    query_string_filtering = 'top_rated'
    if filtering == 'removed':
        query_string_filtering = 'removed'
    elif filtering == '-score':
        query_string_filtering = 'top_rated'
    elif filtering == '-discussed':
        query_string_filtering = 'most_discussed'
    elif filtering == '-created_date':
        query_string_filtering = 'newest'
    elif filtering == '-hot_score':
        query_string_filtering = 'hot'

    request_path = '/api/paper/get_hub_papers/'
    if STAGING:
        http_host = 'staging-backend.researchhub.com'
        protocol = 'https'
    elif PRODUCTION:
        http_host = 'backend.researchhub.com'
        protocol = 'https'
    else:
        http_host = 'localhost:8000'
        protocol = 'http'

    start_date_timestamp = int(start_date.timestamp())
    end_date_timestamp = int(end_date.timestamp())
    query_string = 'page=1&start_date__gte={}&end_date__lte={}&filtering={}&hub_id={}&'.format(
        start_date_timestamp,
        end_date_timestamp,
        query_string_filtering,
        hub_id
    )
    http_meta = {
        'QUERY_STRING': query_string,
        'HTTP_HOST': http_host,
        'HTTP_X_FORWARDED_PROTO': protocol,
    }

    document_view = ResearchhubUnifiedDocumentViewSet()
    http_req = HttpRequest()
    http_req.META = http_meta
    http_req.path = request_path
    req = Request(http_req)
    document_view.request = req

    documents = document_view.get_filtered_queryset(
        document_type,
        filtering,
        hub_id,
        start_date,
        end_date
    )
    page = document_view.paginate_queryset(documents)
    context = document_view._get_serializer_context()
    serializer = DynamicUnifiedDocumentSerializer(
        page,
        _include_fields=[
            'created_by',
            'documents',
            'document_type',
            'hot_score',
            'score'
        ],
        many=True,
        context=context,
    )
    serializer_data = serializer.data

    paginated_response = document_view.get_paginated_response(
        serializer_data
    )

    cache_key_hub = get_cache_key('hub', cache_pk)
    print('+++++++++++++++')
    print('PRELOADING', cache_key_hub)
    print('+++++++++++++++')
    cache.set(
        cache_key_hub,
        paginated_response.data,
        timeout=None
    )

    return paginated_response.data


# Executes every 5 minutes
@periodic_task(
    run_every=crontab(minute='*/5'),
    priority=1,
    options={'queue': f'{APP_ENV}_core_queue'}
)
def preload_hub_documents(
    document_type=ALL.lower(),
    hub_ids=None
):
    from researchhub_document.views import ResearchhubUnifiedDocumentViewSet
    from researchhub_document.serializers import (
      DynamicUnifiedDocumentSerializer
    )

    Hub = apps.get_model('hub.Hub')
    hubs = Hub.objects.all()

    document_view = ResearchhubUnifiedDocumentViewSet()

    if document_type == ALL.lower():
        document_types = [PAPER, ELN, DISCUSSION]
    elif document_type == POSTS.lower():
        document_types = [ELN, DISCUSSION]
    else:
        document_types = [PAPER]

    if hub_ids:
        hubs = hubs.filter(id__in=hub_ids)

    data = []
    for hub in hubs.iterator():
        hub_name = hub.slug
        cache_pk = f'{document_type}_{hub_name}'
        documents = hub.related_documents.get_queryset().filter(
            document_type__in=document_types,
            is_removed=False
        ).order_by(
            '-hot_score'
        )[:20]
        cache_key = get_cache_key('documents', cache_pk)
        context = document_view._get_serializer_context()
        serializer = DynamicUnifiedDocumentSerializer(
            documents,
            _include_fields=[
                'created_by',
                'documents',
                'document_type',
                'hot_score',
                'score'
            ],
            many=True,
            context=context
        )

        serializer_data = serializer.data
        data.append(serializer_data)
        cache.set(
            cache_key,
            serializer_data,
            timeout=None
        )
    return data


@app.task
def update_elastic_registry(post):
    registry.update(post)


@app.task
def invalidate_feed_cache(
    hub_ids,
    filters,
    with_default=True,
    document_types=[
        ALL.lower(),
        POSTS.lower(),
        PAPER.lower(),
        HYPOTHESIS.lower()
    ],
    date_ranges=[
        'today',
        'week',
        'month',
        'year',
        'all_time'
    ],
    reload_cache=True
):
    from researchhub_document.utils import (
        invalidate_most_discussed_cache,
        invalidate_newest_cache,
        invalidate_top_rated_cache,
        invalidate_trending_cache
    )
    from researchhub_document.related_models.constants.filters import (
        DISCUSSED,
        TRENDING,
        NEWEST,
        TOP
    )
    from researchhub_document.utils import reset_unified_document_cache


    if DISCUSSED in filters:
        invalidate_most_discussed_cache(hub_ids, document_types, date_ranges, with_default)
    if TRENDING in filters:
        invalidate_trending_cache(hub_ids, document_types, date_ranges, with_default)
    if NEWEST in filters:
        invalidate_newest_cache(hub_ids, document_types, date_ranges, with_default)
    if TOP in filters:
        invalidate_top_rated_cache(hub_ids, document_types, date_ranges, with_default)

    if reload_cache:
        if with_default:
            hub_ids.append(0)

        reset_unified_document_cache(hub_ids=hub_ids, document_type=document_types, filters=filters, date_ranges=date_ranges)
