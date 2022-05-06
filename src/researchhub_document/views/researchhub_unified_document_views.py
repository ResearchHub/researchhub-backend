from collections import OrderedDict
from datetime import datetime, timedelta
from time import perf_counter

from dateutil import parser
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db.models import Count, Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param
from rest_framework.viewsets import ModelViewSet

from discussion.models import Vote as ReactionVote
from discussion.reaction_serializers import VoteSerializer as ReactionVoteSerializer
from hypothesis.models import Hypothesis
from paper.models import Paper, VotePaperLegacy
from paper.serializers import PaperVoteSerializer
from paper.utils import get_cache_key
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.permissions import HasDocumentCensorPermission
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    ELN,
    HYPOTHESIS,
    PAPER,
    POSTS,
)
from researchhub_document.related_models.constants.filters import (
    DISCUSSED,
    NEWEST,
    TOP,
    TRENDING,
)
from researchhub_document.serializers import (
    DynamicUnifiedDocumentSerializer,
    ResearchhubUnifiedDocumentSerializer,
)
from researchhub_document.utils import (
    get_date_ranges_by_time_scope,
    get_doc_type_key,
    reset_unified_document_cache,
)
from researchhub_document.views.custom.unified_document_pagination import (
    UNIFIED_DOC_PAGE_SIZE,
    UnifiedDocPagination,
)
from user.utils import reset_latest_acitvity_cache


class ResearchhubUnifiedDocumentViewSet(ModelViewSet):
    permission_classes = [
        IsAuthenticated,
    ]
    dynamic_serializer_class = DynamicUnifiedDocumentSerializer
    pagination_class = UnifiedDocPagination
    queryset = ResearchhubUnifiedDocument.objects.all()
    serializer_class = ResearchhubUnifiedDocumentSerializer

    @action(
        detail=True,
        methods=["put", "patch", "delete"],
        permission_classes=[HasDocumentCensorPermission],
    )
    def censor(self, request, pk=None):
        doc = self.get_object()
        doc.is_removed = True
        doc.save()

        doc_type = get_doc_type_key(doc)
        hub_ids = doc.hubs.values_list("id", flat=True)
        reset_unified_document_cache(
            hub_ids,
            document_type=[doc_type, "all"],
            filters=[NEWEST, TOP, TRENDING, DISCUSSED],
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

        doc_type = get_doc_type_key(doc)
        hub_ids = doc.hubs.values_list("id", flat=True)
        reset_unified_document_cache(
            hub_ids,
            document_type=[doc_type, "all"],
            filters=[NEWEST, TOP, TRENDING, DISCUSSED],
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
            filters=[NEWEST, TOP, TRENDING, DISCUSSED],
        )

        return update_response

    def _get_document_filtering(self, query_params):
        filtering = query_params.get("ordering", None)
        if filtering == "removed":
            filtering = "removed"
        elif filtering == "top_rated":
            filtering = "-score"
        elif filtering == "most_discussed":
            filtering = "-discussed"
        elif filtering == "newest":
            filtering = "-created_date"
        elif filtering == "hot":
            filtering = "-hot_score"
        elif filtering == "user_uploaded":
            filtering = "user_uploaded"
        else:
            filtering = "-score"
        return filtering

    def _get_serializer_context(self):
        context = {
            "doc_duds_get_documents": {
                "_include_fields": [
                    "abstract",
                    "aggregate_citation_consensus",
                    "created_by",
                    "created_date",
                    "file",
                    "first_preview",
                    "hot_score",
                    "hubs",
                    "id",
                    "discussion_count",
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
                    "author_profile",
                ]
            },
            "pap_dps_get_uploaded_by": {
                "_include_fields": [
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
        }
        return context

    def get_filtered_queryset(
        self,
        document_type,
        filtering,
        hub_id,
        time_scope,
    ):

        date_ranges = get_date_ranges_by_time_scope(time_scope)
        start_date = date_ranges[0]
        end_date = date_ranges[1]

        papers = Paper.objects.filter(uploaded_by__isnull=False).values_list(
            "unified_document"
        )
        posts = ResearchhubPost.objects.filter(created_by__isnull=False).values_list(
            "unified_document"
        )
        hypothesis = Hypothesis.objects.filter(created_by__isnull=False).values_list(
            "unified_document"
        )
        filtered_ids = papers.union(posts, hypothesis)
        qs = self.queryset.filter(id__in=filtered_ids, is_removed=False)

        if document_type == PAPER.lower():
            qs = qs.filter(document_type=PAPER)
        elif document_type == POSTS.lower():
            qs = qs.filter(document_type__in=[DISCUSSION, ELN])
        elif document_type == HYPOTHESIS.lower():
            qs = qs.filter(document_type=HYPOTHESIS)
        else:
            qs = qs.all()

        hub_id = int(hub_id)
        if hub_id != 0:
            qs = qs.filter(hubs__in=[hub_id])

        if filtering == "removed":
            qs = qs.filter(is_removed=True).order_by("-created_date")
        elif filtering == "-score":
            paper_votes = PaperVote.objects.filter(
                created_date__range=(start_date, end_date)
            ).values_list("paper__unified_document", flat=True)
            post_votes = ResearchhubPost.objects.filter(
                votes__created_date__range=(start_date, end_date)
            ).values_list("unified_document", flat=True)
            hypo_votes = Hypothesis.objects.filter(
                votes__created_date__range=(start_date, end_date)
            ).values_list("unified_document", flat=True)
            unified_document_ids = paper_votes.union(post_votes, hypo_votes)

            qs = qs.filter(id__in=unified_document_ids).order_by(filtering)
        elif filtering == "-discussed":

            # Papers
            paper_threads_Q = Q(
                paper__threads__created_date__range=[start_date, end_date],
                paper__threads__is_removed=False,
                paper__threads__created_by__isnull=False,
            )

            paper_comments_Q = Q(
                paper__threads__comments__created_date__range=[start_date, end_date],
                paper__threads__comments__is_removed=False,
                paper__threads__comments__created_by__isnull=False,
            )

            paper_replies_Q = Q(
                paper__threads__comments__replies__created_date__range=[
                    start_date,
                    end_date,
                ],
                paper__threads__comments__replies__is_removed=False,
                paper__threads__comments__replies__created_by__isnull=False,
            )

            # Posts
            post_threads_Q = Q(
                posts__threads__created_date__range=[start_date, end_date],
                posts__threads__is_removed=False,
                posts__threads__created_by__isnull=False,
            )

            post_comments_Q = Q(
                posts__threads__comments__created_date__range=[start_date, end_date],
                posts__threads__comments__is_removed=False,
                posts__threads__comments__created_by__isnull=False,
            )

            post_replies_Q = Q(
                posts__threads__comments__replies__created_date__range=[
                    start_date,
                    end_date,
                ],
                posts__threads__comments__replies__is_removed=False,
                posts__threads__comments__replies__created_by__isnull=False,
            )

            # Hypothesis
            hypothesis_threads_Q = Q(
                posts__threads__created_date__range=[start_date, end_date],
                posts__threads__is_removed=False,
                posts__threads__created_by__isnull=False,
            )

            hypothesis_comments_Q = Q(
                posts__threads__comments__created_date__range=[start_date, end_date],
                posts__threads__comments__is_removed=False,
                posts__threads__comments__created_by__isnull=False,
            )

            hypothesis_replies_Q = Q(
                posts__threads__comments__replies__created_date__range=[
                    start_date,
                    end_date,
                ],
                posts__threads__comments__replies__is_removed=False,
                posts__threads__comments__replies__created_by__isnull=False,
            )

            paper_threads_count = Count(
                "paper__threads", distinct=True, filter=paper_threads_Q
            )
            paper_comments_count = Count(
                "paper__threads__comments", distinct=True, filter=paper_comments_Q
            )
            paper_replies_count = Count(
                "paper__threads__comments__replies",
                distinct=True,
                filter=paper_replies_Q,
            )
            # Posts
            post_threads_count = Count(
                "posts__threads", distinct=True, filter=post_threads_Q
            )
            post_comments_count = Count(
                "posts__threads__comments", distinct=True, filter=post_comments_Q
            )
            post_replies_count = Count(
                "posts__threads__comments__replies",
                distinct=True,
                filter=post_replies_Q,
            )
            # Hypothesis
            hypothesis_threads_count = Count(
                "hypothesis__threads", distinct=True, filter=hypothesis_threads_Q
            )
            hypothesis_comments_count = Count(
                "hypothesis__threads__comments",
                distinct=True,
                filter=hypothesis_comments_Q,
            )
            hypothesis_replies_count = Count(
                "hypothesis__threads__comments__replies",
                distinct=True,
                filter=hypothesis_replies_Q,
            )

            qs = (
                qs.filter(
                    paper_threads_Q
                    | paper_comments_Q
                    | paper_replies_Q
                    | post_threads_Q
                    | post_comments_Q
                    | post_replies_Q
                    | hypothesis_threads_Q
                    | hypothesis_comments_Q
                    | hypothesis_replies_Q
                )
                .annotate(
                    # Papers
                    paper_threads_count=paper_threads_count,
                    paper_comments_count=paper_comments_count,
                    paper_replies_count=paper_replies_count,
                    # Posts
                    post_threads_count=post_threads_count,
                    post_comments_count=post_comments_count,
                    post_replies_count=post_replies_count,
                    # # Hypothesis
                    hypothesis_threads_count=hypothesis_threads_count,
                    hypothesis_comments_count=hypothesis_comments_count,
                    hypothesis_replies_count=hypothesis_replies_count,
                    # # Add things up
                    discussed=(
                        paper_threads_count
                        + paper_comments_count
                        + paper_replies_count
                        + post_threads_count
                        + post_comments_count
                        + post_replies_count
                        + hypothesis_threads_count
                        + hypothesis_comments_count
                        + hypothesis_replies_count
                    ),
                )
                .order_by("-discussed")
            )
        elif filtering == "-created_date":
            qs = qs.order_by(filtering)
        elif filtering == "-hot_score":
            qs = qs.order_by("-hot_score_v2")
        elif filtering == "user_uploaded":
            qs = qs.filter(
                (
                    Q(paper__uploaded_by__isnull=False)
                    | Q(posts__created_by__isnull=False)
                )
            ).order_by("-created_date")
        else:
            qs = qs.order_by("-hot_score_v2")

        return qs

    def _get_unifed_document_cache_hit(
        self, document_type, filtering, hub_id, page_number, time_scope
    ):
        cache_hit = None
        if page_number == 1 and "removed" not in filtering:
            cache_pk = f"{document_type}_{hub_id}_{filtering}_{time_scope}"
            cache_key_hub = get_cache_key("hub", cache_pk)
            cache_hit = cache.get(cache_key_hub)

        if cache_hit:
            return cache_hit
        return None

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def get_unified_documents(self, request):
        is_anonymous = request.user.is_anonymous
        query_params = request.query_params
        subscribed_hubs = query_params.get("subscribed_hubs", "false")
        time_scope = query_params.get("time", "today")

        if subscribed_hubs == "true" and not is_anonymous:
            return self._get_subscribed_unified_documents(request)

        document_request_type = query_params.get("type", "all")
        hub_id = query_params.get("hub_id", 0)
        page_number = int(query_params.get("page", 1))

        filtering = self._get_document_filtering(query_params)
        cache_hit = self._get_unifed_document_cache_hit(
            document_request_type, filtering, hub_id, page_number, time_scope
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

        documents = self.get_filtered_queryset(
            document_request_type,
            filtering,
            hub_id,
            time_scope,
        )

        context = self._get_serializer_context()
        page = self.paginate_queryset(documents)

        serializer = self.dynamic_serializer_class(
            page,
            _include_fields=[
                "documents",
                "document_type",
                "get_review",
                "hot_score",
                "hot_score_v2",
                "reviews",
                "score",
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
                if isinstance(doc["documents"], list):
                    doc["documents"][0]["score"] = docs_to_score_map[doc["id"]]
                elif isinstance(doc["documents"], dict):
                    doc["documents"]["score"] = docs_to_score_map[doc["id"]]

        return cache_hit

    def _get_subscribed_unified_documents(self, request):
        default_hub_id = 0
        hub_ids = request.user.subscribed_hubs.values_list("id", flat=True)
        query_params = request.query_params
        document_request_type = query_params.get("type", "all")
        time_scope = query_params.get("time", "today")

        page_number = int(query_params.get("page", 1))
        filtering = self._get_document_filtering(query_params)

        all_documents = {}
        for hub_id in hub_ids:
            cache_hit = self._get_unifed_document_cache_hit(
                document_request_type, filtering, hub_id, page_number, time_scope
            )

            if cache_hit:
                cache_hit = self._cache_hit_with_latest_metadata(cache_hit)
                for doc in cache_hit["results"]:
                    if doc["id"] not in all_documents:
                        all_documents[doc["id"]] = doc

        all_documents = list(all_documents.values())
        if len(all_documents) == 0:
            all_documents = self.get_filtered_queryset(
                document_request_type,
                filtering,
                default_hub_id,
                time_scope,
            )
            all_documents = all_documents.filter(hubs__in=hub_ids).distinct()

            context = self._get_serializer_context()
            page = self.paginate_queryset(all_documents)
            serializer = self.dynamic_serializer_class(
                page,
                _include_fields=["documents", "document_type", "hot_score", "score"],
                many=True,
                context=context,
            )
            serializer_data = serializer.data
            return self.get_paginated_response(serializer_data)

        else:
            ordering = query_params.get("ordering", None)
            if ordering == "top_rated":
                sort_key = "score"
            elif ordering == "most_discussed":
                sort_key = "hot_score_v2"
            elif ordering == "newest":
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
            "papers": {},
            "posts": {},
        }

        if user.is_authenticated:
            if paper_ids:
                paper_votes = PaperVote.objects.filter(
                    paper__id__in=paper_ids, created_by=user
                )
                for vote in paper_votes.iterator():
                    paper_id = vote.paper_id
                    response["papers"][paper_id] = PaperVoteSerializer(
                        instance=vote
                    ).data
            if post_ids:
                post_votes = get_user_votes(
                    user, post_ids, ContentType.objects.get_for_model(ResearchhubPost)
                )
                for vote in post_votes.iterator():
                    response["posts"][vote.object_id] = ReactionVoteSerializer(
                        instance=vote
                    ).data
            if hypothesis_ids:
                hypo_votes = get_user_votes(
                    user, hypothesis_ids, ContentType.objects.get_for_model(Hypothesis)
                )
                for vote in hypo_votes.iterator():
                    response["hypothesis"][vote.object_id] = ReactionVoteSerializer(
                        instance=vote
                    ).data
        return Response(response, status=status.HTTP_200_OK)


def get_user_votes(created_by, doc_ids, reaction_content_type):
    return ReactionVote.objects.filter(
        content_type=reaction_content_type, object_id__in=doc_ids, created_by=created_by
    )
