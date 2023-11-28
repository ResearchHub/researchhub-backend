from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.http.request import HttpRequest, QueryDict
from django_elasticsearch_dsl.registries import registry
from rest_framework.request import Request

from paper.utils import get_cache_key
from researchhub.celery import QUEUE_CACHES, QUEUE_ELASTIC_SEARCH, QUEUE_HOT_SCORE, app
from researchhub.settings import PRODUCTION, STAGING
from researchhub_document.related_models.constants.document_type import BOUNTY
from utils import sentry


@app.task(queue=QUEUE_HOT_SCORE)
def recalc_hot_score_task(instance_content_type_id, instance_id):
    content_type = ContentType.objects.get(id=instance_content_type_id)
    model_name = content_type.model
    model_class = content_type.model_class()
    uni_doc = None

    try:
        if model_name in ["hypothesis", "researchhubpost", "paper"]:
            uni_doc = model_class.objects.get(id=instance_id).unified_document
        elif model_name in ["thread", "comment", "reply"]:
            thread = None
            if model_name == "thread":
                thread = model_class.objects.get(id=instance_id)
            elif model_name == "comment":
                comment = model_class.objects.get(id=instance_id)
                thread = comment.parent
            elif model_name == "reply":
                reply = model_class.objects.get(id=instance_id)
                thread = reply.parent.parent

            if thread.paper:
                uni_doc = thread.paper.unified_document
            elif thread.hypothesis:
                uni_doc = thread.hypothesis.unified_document
            elif thread.post:
                uni_doc = thread.post.unified_document
        elif model_name == "paper":
            uni_doc = model_class.objects.get(id=instance_id).unified_document
        elif model_name == "citation":
            uni_doc = model_class.objects.get(id=instance_id).source

        uni_doc.calculate_hot_score_v2(should_save=True)
    except Exception as error:
        sentry.log_error(error)


@app.task(queue=QUEUE_CACHES)
def preload_trending_documents(
    document_type,
    hub_id,
    filtering,
    time_scope,
):
    from researchhub_document.serializers import DynamicUnifiedDocumentSerializer
    from researchhub_document.views import ResearchhubUnifiedDocumentViewSet

    if time_scope == "all":
        cache_pk = f"{document_type}_{hub_id}_{filtering}_all"
    elif time_scope == "year":
        cache_pk = f"{document_type}_{hub_id}_{filtering}_year"
    elif time_scope == "month":
        cache_pk = f"{document_type}_{hub_id}_{filtering}_month"
    elif time_scope == "week":
        cache_pk = f"{document_type}_{hub_id}_{filtering}_week"
    else:  # Today
        cache_pk = f"{document_type}_{hub_id}_{filtering}_today"

    request_path = "/api/researchhub_unified_document/get_unified_documents/"
    if STAGING:
        http_host = "staging-backend.researchhub.com"
        protocol = "https"
    elif PRODUCTION:
        http_host = "backend.researchhub.com"
        protocol = "https"
    else:
        http_host = "localhost:8000"
        protocol = "http"

    if hub_id == 0:
        hub_id = ""

    query_string = f"page=1&time={time_scope}&ordering={filtering}&hub_id={hub_id}&type={document_type}"

    if hub_id == "":
        query_string = f"{query_string}&ignore_excluded_homepage=true"

    if document_type == BOUNTY.lower():
        query_string = f"{query_string}&tags=open"
    http_meta = {
        "QUERY_STRING": query_string,
        "HTTP_HOST": http_host,
        "HTTP_X_FORWARDED_PROTO": protocol,
    }
    query_dict = QueryDict(query_string=query_string)

    document_view = ResearchhubUnifiedDocumentViewSet()
    document_view.action = "list"
    http_req = HttpRequest()
    http_req.META = http_meta
    http_req.path = request_path
    http_req.GET = query_dict
    req = Request(http_req)
    document_view.request = req

    documents = document_view.get_filtered_queryset()
    page = document_view.paginate_queryset(documents)
    context = document_view._get_serializer_context()
    serializer = DynamicUnifiedDocumentSerializer(
        page,
        _include_fields=[
            "created_date",
            "id",
            "documents",
            "document_type",
            "hot_score",
            "hot_score_v2",
            "reviews",
            "score",
            "bounties",
        ],
        many=True,
        context=context,
    )

    serializer_data = serializer.data

    paginated_response = document_view.get_paginated_response(serializer_data)
    cache_key_hub = get_cache_key("hub", cache_pk)
    cache.set(cache_key_hub, paginated_response.data, timeout=None)

    return paginated_response.data


@app.task(queue=QUEUE_ELASTIC_SEARCH)
def update_elastic_registry(post):
    registry.update(post)
