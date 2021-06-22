from datetime import datetime, timedelta

from celery.decorators import periodic_task
from celery.task.schedules import crontab
from django.apps import apps
from django.http.request import HttpRequest
from django.core.cache import cache
from rest_framework.request import Request

from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    ELN,
    PAPER,
    POSTS,
    ALL,
)
from paper.utils import get_cache_key
from researchhub.celery import app
from researchhub.settings import (
    APP_ENV,
    STAGING,
    PRODUCTION,
)


@app.task
def preload_trending_documents(
    document_type,
    hub_id,
    ordering,
    time_difference
):
    from researchhub_document.views import ResearchhubUnifiedDocumentViewSet
    from researchhub_document.serializers import (
      ResearchhubUnifiedDocumentSerializer
    )

    initial_date = datetime.now().replace(
        hour=7,
        minute=0,
        second=0,
        microsecond=0
    )
    end_date = datetime.now()
    if time_difference > 365:
        cache_pk = f'{document_type}_{hub_id}_{ordering}_all_time'
        start_date = datetime(
            year=2018,
            month=12,
            day=31,
            hour=7
        )
    elif time_difference == 365:
        cache_pk = f'{document_type}_{hub_id}_{ordering}_year'
        start_date = initial_date - timedelta(days=365)
    elif time_difference == 30 or time_difference == 31:
        cache_pk = f'{document_type}_{hub_id}_{ordering}_month'
        start_date = initial_date - timedelta(days=30)
    elif time_difference == 7:
        cache_pk = f'{document_type}_{hub_id}_{ordering}_week'
        start_date = initial_date - timedelta(days=7)
    else:
        start_date = datetime.now().replace(
            hour=7,
            minute=0,
            second=0,
            microsecond=0
        )
        cache_pk = f'{document_type}_{hub_id}_{ordering}_today'

    query_string_ordering = 'top_rated'
    if ordering == 'removed':
        query_string_ordering = 'removed'
    elif ordering == '-score':
        query_string_ordering = 'top_rated'
    elif ordering == '-discussed':
        query_string_ordering = 'most_discussed'
    elif ordering == '-uploaded_date':
        query_string_ordering = 'newest'
    elif ordering == '-hot_score':
        query_string_ordering = 'hot'

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
    query_string = 'page=1&start_date__gte={}&end_date__lte={}&ordering={}&hub_id={}&'.format(
        start_date_timestamp,
        end_date_timestamp,
        query_string_ordering,
        hub_id
    )
    http_meta = {
        'QUERY_STRING': query_string,
        'HTTP_HOST': http_host,
        'HTTP_X_FORWARDED_PROTO': protocol,
    }

    cache_key_hub = get_cache_key('hub', cache_pk)
    document_view = ResearchhubUnifiedDocumentViewSet()
    http_req = HttpRequest()
    http_req.META = http_meta
    http_req.path = request_path
    req = Request(http_req)
    document_view.request = req

    documents = document_view.get_filtered_queryset(
        document_type,
        query_string_ordering,
        hub_id,
        start_date,
        end_date
    )
    page = document_view.paginate_queryset(documents)
    serializer = ResearchhubUnifiedDocumentSerializer(page, many=True)
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


# Executes every 5 minutes
@periodic_task(
    run_every=crontab(minute='*/5'),
    priority=1,
    options={'queue': f'{APP_ENV}_core_queue'}
)
def preload_hub_documents(document_type, hub_ids=None):
    from researchhub_document.serializers import (
      ResearchhubUnifiedDocumentSerializer
    )

    Hub = apps.get_model('hub.Hub')
    hubs = Hub.objects.all()

    context = {}
    context['user_no_balance'] = True

    if document_type == ALL.lower():
        document_types = [PAPER, ELN, DISCUSSION]
    elif document_type == POSTS.lower():
        document_types = [ELN, DISCUSSION]
    else:
        document_types = [PAPER]

    if hub_ids:
        hubs = hubs.filter(id__in=hub_ids)

    for hub in hubs.iterator():
        hub_name = hub.slug
        cache_pk = f'{document_type}_{hub_name}'
        documents = hub.related_documents.get_queryset().filter(
            document_type__in=document_types,
            is_removed=False
        ).order_by(
            '-hot_score'
        )[:10]
        cache_key = get_cache_key('documents', cache_pk)
        serializer = ResearchhubUnifiedDocumentSerializer(
            documents,
            many=True,
            context=context
        )

        cache.set(
            cache_key,
            serializer.data,
            timeout=None
        )
    return serializer.data
