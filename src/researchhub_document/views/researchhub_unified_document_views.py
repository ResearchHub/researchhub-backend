from time import perf_counter

from dateutil import parser
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param
from rest_framework.viewsets import ModelViewSet

from discussion.models import Vote as GrmVote
from discussion.reaction_serializers import VoteSerializer as GrmVoteSerializer
from hypothesis.models import Hypothesis
from paper.models import Paper
from paper.utils import get_cache_key
from researchhub_document.filters import UnifiedDocumentFilter
from researchhub_document.models import (
    FeaturedContent,
    ResearchhubPost,
    ResearchhubUnifiedDocument,
)
from researchhub_document.permissions import HasDocumentCensorPermission
from researchhub_document.related_models.constants.document_type import (
    FILTER_EXCLUDED_FROM_FEED,
    FILTER_INCLUDED_IN_FEED,
)
from researchhub_document.related_models.constants.filters import (
    DISCUSSED,
    EXPIRING_SOON,
    HOT,
    MOST_RSC,
    NEW,
    UPVOTED,
)
from researchhub_document.serializers import (
    DynamicUnifiedDocumentSerializer,
    ResearchhubUnifiedDocumentSerializer,
)
from researchhub_document.utils import get_doc_type_key, reset_unified_document_cache
from researchhub_document.views.custom.unified_document_pagination import (
    UNIFIED_DOC_PAGE_SIZE,
    UnifiedDocPagination,
)
from user.permissions import IsModerator
from user.utils import reset_latest_acitvity_cache
from utils.permissions import ReadOnly


class ResearchhubUnifiedDocumentViewSet(ModelViewSet):
    permission_classes = [
        IsAuthenticated | ReadOnly,
    ]
    dynamic_serializer_class = DynamicUnifiedDocumentSerializer
    pagination_class = UnifiedDocPagination
    queryset = ResearchhubUnifiedDocument.objects.all()
    filter_backends = (DjangoFilterBackend,)
    filter_class = UnifiedDocumentFilter
    serializer_class = ResearchhubUnifiedDocumentSerializer

    def create(self, *args, **kwargs):
        return Response(status=403)

    def list(self, *args, **kwargs):
        return Response(status=403)

    def retrieve(self, *args, **kwargs):
        return Response(status=403)

    def partial_update(self, *args, **kwargs):
        return Response(status=403)

    def destroy(self, *args, **kwargs):
        return Response(status=403)

    @action(
        detail=True,
        methods=["put", "patch", "delete"],
        permission_classes=[HasDocumentCensorPermission],
    )
    def censor(self, request, pk=None):
        doc = self.get_object()
        doc.is_removed = True
        doc.save()

        inner_doc = doc.get_document()
        if isinstance(inner_doc, Paper):
            inner_doc.is_removed = True
            inner_doc.save()
            # Commenting out paper cache
            # inner_doc.reset_cache(use_celery=False)

        action = inner_doc.actions
        if action.exists():
            action = action.first()
            action.is_removed = True
            action.display = False
            action.save()

        doc_type = get_doc_type_key(doc)
        hub_ids = doc.hubs.values_list("id", flat=True)
        reset_unified_document_cache(
            hub_ids,
            document_type=[doc_type, "all"],
            filters=[NEW, UPVOTED, HOT, DISCUSSED, MOST_RSC, EXPIRING_SOON],
            with_default_hub=True,
        )
        return Response(self.get_serializer(instance=doc).data, status=200)

    @action(
        detail=True,
        methods=["put", "patch"],
        permission_classes=[HasDocumentCensorPermission],
    )
    def restore(self, request, pk=None):
        doc = self.get_object()
        doc.is_removed = False
        doc.save()

        inner_doc = doc.get_document()
        if isinstance(inner_doc, Paper):
            inner_doc.is_removed = False
            inner_doc.save()
            # Commenting out paper cache
            # inner_doc.reset_cache(use_celery=False)

        action = inner_doc.actions
        if action.exists():
            action = action.first()
            action.is_removed = False
            action.display = True
            action.save()

        doc_type = get_doc_type_key(doc)
        hub_ids = doc.hubs.values_list("id", flat=True)
        reset_unified_document_cache(
            hub_ids,
            document_type=[doc_type, "all"],
            filters=[NEW, UPVOTED, HOT, DISCUSSED, MOST_RSC, EXPIRING_SOON],
        )

        return Response(self.get_serializer(instance=doc).data, status=200)

    @action(
        detail=True,
        methods=["get"],
        permission_classes=[AllowAny],
    )
    def hot_score(self, request, pk=None):
        debug = request.query_params.get("debug", False) == "true"

        if debug:
            time_start = perf_counter()

        doc = self.get_object()
        hot_score_tpl = doc.calculate_hot_score_v2(debug)

        if debug:
            time_stop = perf_counter()
            elapsed_time = str((time_stop - time_start) * 1000) + "ms"
            debug_obj = hot_score_tpl[1]
            debug_obj["query_time"] = elapsed_time
            return Response(hot_score_tpl[1], status=status.HTTP_200_OK)
        else:
            return Response({"score": hot_score_tpl[0]}, status=status.HTTP_200_OK)

    def update(self, request, *args, **kwargs):
        update_response = super().update(request, *args, **kwargs)

        hub_ids = list(self.get_object().hubs.values_list("pk", flat=True))
        hub_ids.append(0)

        reset_latest_acitvity_cache(",".join([str(hub_id) for hub_id in hub_ids]))

        doc = self.get_object()
        doc_type = get_doc_type_key(doc)
        reset_unified_document_cache(
            hub_ids,
            document_type=[doc_type, "all"],
            filters=[NEW, UPVOTED, HOT, DISCUSSED],
        )

        return update_response

    def _get_serializer_context(self):
        context = {
            "doc_duds_get_documents": {
                "_include_fields": [
                    "abstract",
                    "aggregate_citation_consensus",
                    "created_by",
                    "created_date",
                    "discussion_count",
                    "file",
                    "first_preview",
                    "has_accepted_answer",
                    "hot_score",
                    "hubs",
                    "id",
                    "boost_amount",
                    "paper_title",
                    "pdf_url",
                    "preview_img",
                    "renderable_text",
                    "score",
                    "slug",
                    "title",
                    "uploaded_by",
                    "uploaded_date",
                ]
            },
            "doc_duds_get_bounties": {
                "_include_fields": [
                    "amount",
                    "created_by",
                    "content_type",
                    "id",
                    "item",
                    "item_object_id",
                    "expiration_date",
                    "status",
                ],
            },
            "doc_dps_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "is_locked",
                    "slug",
                    "is_removed",
                    "hub_image",
                ]
            },
            "pap_dps_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "is_locked",
                    "slug",
                    "is_removed",
                    "hub_image",
                ]
            },
            "pap_dps_get_unified_document": {
                "_include_fields": [
                    "id",
                    "title",
                    "slug",
                    "reviews",
                ]
            },
            "doc_dps_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "doc_dps_get_threads": {
                "_include_fields": [
                    "bounties",
                ]
            },
            "pap_dps_get_uploaded_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "usr_dus_get_author_profile": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                ]
            },
            "doc_duds_get_created_by": {
                "_include_fields": [
                    "author_profile",
                ]
            },
            "hyp_dhs_get_created_by": {
                "_include_fields": [
                    "author_profile",
                ]
            },
            "hyp_dhs_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "is_locked",
                    "slug",
                    "is_removed",
                    "hub_image",
                ]
            },
            "rep_dbs_get_created_by": {"_include_fields": ["author_profile", "id"]},
            "rep_dbs_get_item": {
                "_include_fields": [
                    "plain_text",
                ]
            },
        }
        return context

    def _get_featured_documents_queryset(self):
        featured_content = FeaturedContent.objects.all().values_list("unified_document")
        qs = self.get_queryset().filter(id__in=featured_content)
        return qs

    def get_filtered_queryset(self):
        qs = self.get_queryset().filter(is_removed=False)
        qs = self.filter_queryset(qs)
        return qs

    def _get_unified_document_cache_hit(
        self, document_type, filtering, hub_id, page_number, time_scope
    ):
        cache_hit = None
        if page_number == 1:
            cache_pk = f"{document_type}_{hub_id}_{filtering}_{time_scope}"
            cache_key_hub = get_cache_key("hub", cache_pk)
            cache_hit = cache.get(cache_key_hub)

        if cache_hit:
            return cache_hit
        return None

    @action(detail=False, methods=["get"], permission_classes=[IsModerator])
    def test_get_unified_documents(self, request):
        # This method is loads the feed without the cache
        query_params = request.query_params
        hub_id = query_params.get("hub_id", 0) or 0

        documents = self.get_filtered_queryset()
        context = self._get_serializer_context()
        context["hub_id"] = hub_id
        page = self.paginate_queryset(documents)
        _include_fields = [
            "id",
            "created_date",
            "documents",
            "document_type",
            "hot_score",
            "hot_score_v2",
            "reviews",
            "score",
            "bounties",
            "concepts",
        ]
        serializer = self.dynamic_serializer_class(
            page,
            _include_fields=_include_fields,
            many=True,
            context=context,
        )
        serializer_data = serializer.data

        return self.get_paginated_response(serializer_data)

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def get_unified_documents(self, request):
        is_anonymous = request.user.is_anonymous
        query_params = request.query_params
        subscribed_hubs = query_params.get("subscribed_hubs", "false")
        filtering = query_params.get("ordering", HOT)
        time_scope = query_params.get("time", "today")

        if subscribed_hubs == "true" and not is_anonymous:
            return self._get_subscribed_unified_documents(request)

        document_request_type = query_params.get("type", "all")
        hub_id = query_params.get("hub_id", 0) or 0
        page_number = int(query_params.get("page", 1))

        cache_hit = self._get_unified_document_cache_hit(
            document_request_type,
            filtering,
            hub_id,
            page_number,
            time_scope,
        )

        if cache_hit and page_number == 1:
            cache_hit = self._cache_hit_with_latest_metadata(cache_hit)
            return Response(cache_hit)
        elif not cache_hit and page_number == 1:
            with_default_hub = True if hub_id == 0 else False
            reset_unified_document_cache(
                hub_ids=[hub_id],
                document_type=[document_request_type],
                filters=[filtering],
                date_ranges=[time_scope],
                with_default_hub=with_default_hub,
            )

        documents = self.get_filtered_queryset()
        context = self._get_serializer_context()
        context["hub_id"] = hub_id
        page = self.paginate_queryset(documents)
        serializer = self.dynamic_serializer_class(
            page,
            _include_fields=[
                "id",
                "created_date",
                "documents",
                "document_type",
                "hot_score",
                "hot_score_v2",
                "reviews",
                "score",
                "bounties",
                "concepts",
            ],
            many=True,
            context=context,
        )
        serializer_data = serializer.data

        return self.get_paginated_response(serializer_data)

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def get_featured_documents(self, request):
        featured_documents = self._get_featured_documents_queryset()
        context = self._get_serializer_context()
        page = self.paginate_queryset(featured_documents)
        serializer = self.dynamic_serializer_class(
            page,
            _include_fields=[
                "id",
                "created_date",
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

        return self.get_paginated_response(serializer_data)

    def _cache_hit_with_latest_metadata(self, cache_hit):
        ids = [d["id"] for d in cache_hit["results"]]
        docs_in_cache = ResearchhubUnifiedDocument.objects.filter(id__in=ids).values(
            "id", "score"
        )
        docs_to_score_map = {d["id"]: d["score"] for d in docs_in_cache}
        for doc in cache_hit["results"]:
            doc.score = docs_to_score_map[doc["id"]]

            if "documents" in doc:
                documents = doc["documents"]
                if isinstance(documents, list) and len(documents) > 0:
                    documents[0]["score"] = docs_to_score_map[doc["id"]]
                elif isinstance(documents, dict):
                    documents["score"] = docs_to_score_map[doc["id"]]
        return cache_hit

    def _get_subscribed_unified_documents(self, request):
        hub_ids = request.user.subscribed_hubs.values_list("id", flat=True)
        query_params = request.query_params
        document_request_type = query_params.get("type", "all")
        time_scope = query_params.get("time", "today")
        filtering = query_params.get("ordering", HOT)
        tags = query_params.get("tags", None)
        page_number = int(query_params.get("page", 1))

        all_documents = {}
        if not tags:
            for hub_id in hub_ids:
                cache_hit = self._get_unified_document_cache_hit(
                    document_request_type,
                    filtering,
                    hub_id,
                    page_number,
                    time_scope,
                )

                if cache_hit:
                    cache_hit = self._cache_hit_with_latest_metadata(cache_hit)
                    for doc in cache_hit["results"]:
                        if doc["id"] not in all_documents:
                            all_documents[doc["id"]] = doc

        all_documents = list(all_documents.values())
        if len(all_documents) == 0:
            all_documents = self.get_filtered_queryset()

            context = self._get_serializer_context()
            page = self.paginate_queryset(all_documents)
            serializer = self.dynamic_serializer_class(
                page,
                _include_fields=[
                    "id",
                    "created_date",
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
            return self.get_paginated_response(serializer_data)

        else:
            ordering = query_params.get("ordering", None)
            if ordering == UPVOTED:
                sort_key = "score"
            elif ordering == DISCUSSED:
                sort_key = "hot_score_v2"
            elif ordering == NEW:
                sort_key = "created_date"
            else:
                sort_key = "hot_score_v2"

            def compare(doc):
                if sort_key == "created_date":
                    return -parser.parse(doc["created_date"]).timestamp()
                else:
                    return -doc[sort_key]

            all_documents = sorted(all_documents, key=compare)
            all_documents = all_documents[:UNIFIED_DOC_PAGE_SIZE]
            next_page = request.build_absolute_uri()
            if len(all_documents) < UNIFIED_DOC_PAGE_SIZE:
                next_page = None
            else:
                next_page = replace_query_param(next_page, "page", 2)
            res = {
                "count": len(all_documents),
                "next": next_page,
                "results": all_documents,
            }
            return Response(res, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], permission_classes=[IsModerator])
    def exclude_from_feed(self, request, pk=None):
        unified_document = self.get_object()
        unified_document.update_filter(FILTER_EXCLUDED_FROM_FEED)

        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], permission_classes=[IsModerator])
    def feature_document(self, request, pk=None):
        unified_document = self.get_object()
        doc_type = get_doc_type_key(unified_document)
        hub_ids = list(unified_document.hubs.values_list("id", flat=True))

        if request.data["feature_in_homepage"] is True:
            FeaturedContent.objects.get_or_create(
                unified_document=unified_document, hub_id=None
            )

        if request.data["feature_in_hubs"] is True:
            for hub_id in hub_ids:
                FeaturedContent.objects.get_or_create(
                    unified_document=unified_document, hub_id=hub_id
                )

        hub_ids.append(0)
        reset_unified_document_cache(
            hub_ids,
            document_type=["all", doc_type],
            filters=[HOT],
            with_default_hub=True,
        )

        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], permission_classes=[IsModerator])
    def remove_from_featured(self, request, pk=None):
        unified_document = self.queryset.get(id=pk)
        doc_type = get_doc_type_key(unified_document)
        hub_ids = list(unified_document.hubs.values_list("id", flat=True))
        hub_ids.append(0)

        FeaturedContent.objects.filter(unified_document=unified_document).delete()

        reset_unified_document_cache(
            hub_ids,
            document_type=["all", doc_type],
            filters=[HOT],
            with_default_hub=True,
        )

        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], permission_classes=[IsModerator])
    def include_in_feed(self, request, pk=None):
        unified_document = self.get_object()
        unified_document.update_filter(FILTER_INCLUDED_IN_FEED)
        return Response(status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def check_user_vote(self, request):
        paper_ids = request.query_params.get("paper_ids", "")
        post_ids = request.query_params.get("post_ids", "")
        hypothesis_ids = request.query_params.get("hypothesis_ids", "")

        if paper_ids:
            paper_ids = paper_ids.split(",")
        if post_ids:
            post_ids = post_ids.split(",")
        if hypothesis_ids:
            hypothesis_ids = hypothesis_ids.split(",")

        user = request.user
        response = {
            "hypothesis": {},
            "paper": {},
            "posts": {},
        }

        if user.is_authenticated:
            # TODO: Refactor below
            if paper_ids:
                paper_votes = get_user_votes(
                    user, paper_ids, ContentType.objects.get_for_model(Paper)
                )
                for vote in paper_votes.iterator():
                    paper_id = vote.object_id
                    response["paper"][paper_id] = GrmVoteSerializer(instance=vote).data
            if post_ids:
                post_votes = get_user_votes(
                    user, post_ids, ContentType.objects.get_for_model(ResearchhubPost)
                )
                for vote in post_votes.iterator():
                    response["posts"][vote.object_id] = GrmVoteSerializer(
                        instance=vote
                    ).data
            if hypothesis_ids:
                hypo_votes = get_user_votes(
                    user, hypothesis_ids, ContentType.objects.get_for_model(Hypothesis)
                )
                for vote in hypo_votes.iterator():
                    response["hypothesis"][vote.object_id] = GrmVoteSerializer(
                        instance=vote
                    ).data
        return Response(response, status=status.HTTP_200_OK)


def get_user_votes(created_by, doc_ids, reaction_content_type):
    return GrmVote.objects.filter(
        content_type=reaction_content_type, object_id__in=doc_ids, created_by=created_by
    )
