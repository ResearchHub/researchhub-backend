from datetime import datetime, timedelta
from django_elasticsearch_dsl.registries import registry

from celery.decorators import periodic_task
from celery.task.schedules import crontab
from django.apps import apps
from django.http.request import HttpRequest
from django.core.cache import cache
from rest_framework.request import Request
from django.db.models.query import QuerySet

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

        uni_doc.calculate_hot_score_v2(should_save=True)
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

    if time_scope == 'all_time':
        cache_pk = f'{document_type}_{hub_id}_{filtering}_all_time'
    elif time_scope == 'year':
        cache_pk = f'{document_type}_{hub_id}_{filtering}_year'
    elif time_scope == 'month':
        cache_pk = f'{document_type}_{hub_id}_{filtering}_month'
    elif time_scope == 'week':
        cache_pk = f'{document_type}_{hub_id}_{filtering}_week'
    else: # Today
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

    query_string = 'page=1&time={}&ordering={}&hub_id={}&'.format(
        time_scope,
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
        time_scope
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
            'score',
            'id',
        ],
        many=True,
        context=context,
    )
    serializer_data = serializer.data

    paginated_response = document_view.get_paginated_response(
        serializer_data
    )

    cache_key_hub = get_cache_key('hub', cache_pk)
    cache.set(
        cache_key_hub,
        paginated_response.data,
        timeout=None
    )

    return paginated_response.data


@periodic_task(
    run_every=crontab(minute='*/15'),
    priority=1,
    options={'queue': f'{APP_ENV}_core_queue'}
)
def preload_homepage_feed():
    from researchhub_document.utils import (
        reset_unified_document_cache,
    )
    reset_unified_document_cache([0])

# Executes every 5 minutes
@periodic_task(
    run_every=crontab(minute='*/25'),
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

