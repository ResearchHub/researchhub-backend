from time import perf_counter

import boto3
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
from hub.models import Hub
from paper.models import Paper
from paper.utils import get_cache_key
from researchhub.settings import AWS_REGION_NAME
from researchhub_document.filters import TIME_SCOPE_CHOICES, UnifiedDocumentFilter
from researchhub_document.models import (
    FeaturedContent,
    ResearchhubPost,
    ResearchhubUnifiedDocument,
)
from researchhub_document.permissions import HasDocumentCensorPermission
from researchhub_document.related_models.constants.document_type import (
    FILTER_EXCLUDED_IN_FEED,
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
from researchhub_document.utils import (
    get_date_ranges_by_time_scope,
    get_doc_type_key,
    reset_unified_document_cache,
)
from user.permissions import IsModerator
from user.utils import reset_latest_acitvity_cache
from utils.aws import PERSONALIZE, get_arn
from utils.permissions import ReadOnly


class UnifiedDocumentPaginator:
    LARGE_HUB_THRESHOLD = 1000
    PAGE_SIZE = 30

    def build_queryset(
        self,
        hub_id=0,
        sort="-hot_score_v2",
        initial_queryset=None,
        page_number=1,
        page_size=None,
    ):
        """
        Consistent query strategy using offset/limit for all cases
        Returns only the results list, letting the view handle pagination links
        """

        if initial_queryset is None:
            # Base query
            base_qs = ResearchhubUnifiedDocument.objects.filter(is_removed=False)
        else:
            base_qs = initial_queryset

        if hub_id == 0:
            hub_size = None
        else:
            base_qs = base_qs.filter(hubs__id=hub_id)
            # Get hub size
            hub_size = Hub.objects.get(id=hub_id).paper_count

        if hub_size is None or hub_size > self.LARGE_HUB_THRESHOLD:
            # For large hubs, use direct limit
            qs = base_qs
        else:
            # For small hubs, get IDs first but still use limit
            doc_ids = list(base_qs.values_list("id", flat=True))
            qs = base_qs.filter(id__in=doc_ids)

        return qs


class ResearchhubUnifiedDocumentViewSet(ModelViewSet):
    permission_classes = [
        IsAuthenticated | ReadOnly,
    ]
    dynamic_serializer_class = DynamicUnifiedDocumentSerializer
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

    def get_queryset(self):
        if self.action == "restore":
            return ResearchhubUnifiedDocument.all_objects.all()
        return super().get_queryset()

    def _get_unified_doc_ids_from_rec_ids(self, rec_ids):
        rec_ids = [item_id.split("_") for item_id in rec_ids if "_" in item_id]
        paper_ids = [
            analytics_id[1] for analytics_id in rec_ids if analytics_id[0] == "paper"
        ]
        post_ids = [
            analytics_id[1]
            for analytics_id in rec_ids
            if analytics_id[0] == "question" or analytics_id[0] == "post"
        ]

        unified_doc_ids = list(
            Paper.objects.filter(id__in=paper_ids).values_list(
                "unified_document", flat=True
            )
        )
        unified_doc_ids.extend(
            list(
                ResearchhubPost.objects.filter(id__in=post_ids).values_list(
                    "unified_document", flat=True
                )
            )
        )

        return unified_doc_ids

    def _exclude_unacceptable_rec_ids(self, rec_ids):
        return [
            rec_id
            for rec_id in rec_ids
            if "_" in rec_id and rec_id.split("_")[0] in ["paper", "question", "post"]
        ]

    def _get_recommendation_buckets(self, user_id):
        personalize_runtime = boto3.client(
            "personalize-runtime", region_name=AWS_REGION_NAME
        )

        user_ranking_arn = get_arn(PERSONALIZE, "campaign/user-ranking")

        buckets = [
            {
                "name": "rh-hot-score",
                "source": "researchhub",
                "num_results": 100,
                "dist_pct": 0.3,
            },
            {
                "name": "highly-cited",
                "source": "personalize",
                "campaign_arn": get_arn(PERSONALIZE, "campaign/recommendations"),
                "filter_arn": get_arn(PERSONALIZE, "filter/highly-cited"),
                "num_results": 100,
                "dist_pct": 0.1,
            },
            {
                "name": "trending-citations",
                "source": "personalize",
                "campaign_arn": get_arn(PERSONALIZE, "campaign/recommendations"),
                "filter_arn": get_arn(PERSONALIZE, "filter/trending-citations"),
                "num_results": 100,
                "dist_pct": 0.25,
            },
            {
                "name": "popular-on-social-media",
                "source": "personalize",
                "campaign_arn": get_arn(PERSONALIZE, "campaign/recommendations"),
                "filter_arn": get_arn(PERSONALIZE, "filter/popular-on-social-media"),
                "num_results": 100,
                "dist_pct": 0.1,
            },
            {
                "name": "only-papers",
                "source": "personalize",
                "campaign_arn": get_arn(PERSONALIZE, "campaign/recommendations"),
                "filter_arn": get_arn(PERSONALIZE, "filter/only-papers"),
                "num_results": 100,
                "dist_pct": 0.1,
            },
            {
                "name": "trending-on-rh",
                "source": "personalize",
                "campaign_arn": get_arn(PERSONALIZE, "campaign/trending"),
                "filter_arn": None,
                "num_results": 100,
                "dist_pct": 0.15,
            },
        ]

        for bucket in buckets:
            if bucket["source"] == "researchhub":
                if bucket["name"] == "rh-hot-score":
                    unified_doc_ids = list(
                        ResearchhubUnifiedDocument.objects.filter(
                            document_type__in=["PAPER", "QUESTION", "DISCUSSION"]
                        )
                        .order_by("-hot_score_v2")[: bucket["num_results"]]
                        .values_list("id", flat=True)
                    )
                    bucket["unified_doc_ids"] = unified_doc_ids
            else:
                args = {
                    "campaignArn": bucket["campaign_arn"],
                    "userId": str(user_id),
                    "numResults": bucket["num_results"],
                }

                if bucket["filter_arn"]:
                    args["filterArn"] = bucket["filter_arn"]

                response = personalize_runtime.get_recommendations(**args)
                rec_ids = [item["itemId"] for item in response["itemList"]]

                rec_ids = self._exclude_unacceptable_rec_ids(rec_ids)

                response = personalize_runtime.get_personalized_ranking(
                    campaignArn=user_ranking_arn,
                    inputList=rec_ids,
                    userId=str(user_id),
                )
                ranked_ids = [
                    item["itemId"] for item in response["personalizedRanking"]
                ]

                unified_doc_ids = self._get_unified_doc_ids_from_rec_ids(ranked_ids)
                bucket["unified_doc_ids"] = unified_doc_ids

        return self._deduplicate_recommendations(buckets)

    def _deduplicate_recommendations(self, buckets):
        seen_doc_ids = set()
        new_buckets = []

        for bucket in buckets:
            new_doc_ids = []
            for doc_id in bucket["unified_doc_ids"]:
                if doc_id not in seen_doc_ids:
                    seen_doc_ids.add(doc_id)
                    new_doc_ids.append(doc_id)

            # Update the bucket with the deduplicated list of doc IDs
            new_bucket = bucket.copy()
            new_bucket["unified_doc_ids"] = new_doc_ids
            new_buckets.append(new_bucket)

        # Replace the original buckets with the deduplicated version
        buckets = new_buckets

        return buckets

    def _build_recommendation_pages(
        self, recommendation_buckets, num_pages_to_build, num_per_page
    ):
        pages = []
        for i in range(num_pages_to_build):
            this_page = []
            for bucket in recommendation_buckets:
                bucket_items_per_page = int(num_per_page * bucket["dist_pct"])
                doc_ids = bucket["unified_doc_ids"][:bucket_items_per_page]
                docs = ResearchhubUnifiedDocument.objects.filter(id__in=doc_ids)

                for doc in docs:
                    doc.recommendation_metadata = bucket
                    this_page.append(doc)

                bucket["unified_doc_ids"] = bucket["unified_doc_ids"][
                    bucket_items_per_page:
                ]

            pages.append(this_page)

        return pages

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def recommendations(self, request, *args, **kwargs):
        page_number = int(request.query_params.get("page", 1))
        ignore_cache = request.query_params.get("ignore_cache", False) == "true"
        if request.query_params.get("user_id", None):
            user_id = int(request.query_params.get("user_id"))
        elif request.user.is_authenticated:
            user_id = request.user.id
        else:
            # For logged out users and all other cases, let's deafult to "hot" results
            qs = self.get_queryset().order_by("-hot_score_v2")[:20]
            page = self.paginate_queryset(qs)
            context = self._get_serializer_context()
            serializer = self.dynamic_serializer_class(
                page,
                _include_fields=[
                    "id",
                    "created_date",
                    "documents",
                    "document_filter",
                    "document_type",
                    "hot_score",
                    "hubs",
                    "reviews",
                    "score",
                    "fundraise",
                ],
                many=True,
                context=context,
            )

            serializer_data = serializer.data
            return self.get_paginated_response(serializer_data)

        # Session ID will be used to log impressions. It is essential to associate impressions with a user's session
        session_id = request.session.session_key
        if not session_id:
            # If there isn't a session yet, accessing any session attribute will create one.
            request.session["init"] = True
            request.session.save()
            session_id = request.session.session_key
            print("Session ID:", session_id)

        cache_key = f"recs-user-{user_id}-page-{page_number}"
        cache_hit = cache.get(cache_key)

        if cache_hit and not ignore_cache:
            print("cache hit")
            return Response(cache_hit)

        recommendation_buckets = self._get_recommendation_buckets(user_id)
        pages = self._build_recommendation_pages(recommendation_buckets, 5, 20)

        serialized_data_pages = []
        i = 1
        for unified_docs in pages:
            context = self._get_serializer_context()
            cache_key = f"recs-user-{user_id}-page-{i}"
            serializer = self.dynamic_serializer_class(
                unified_docs,
                _include_fields=[
                    "id",
                    "created_date",
                    "documents",
                    "document_filter",
                    "document_type",
                    "hot_score",
                    "hubs",
                    "reviews",
                    "score",
                    "fundraise",
                    "recommendation_metadata",
                ],
                many=True,
                context=context,
            )

            data = {
                "count": len(unified_docs),
                "previous": (
                    f"{request.scheme}://{request.get_host()}/api/researchhub_unified_document/recommendations/?user_id={user_id}&page={i - 1}"
                    if i > 1
                    else None
                ),
                "next": f"{request.scheme}://{request.get_host()}/api/researchhub_unified_document/recommendations/?user_id={user_id}&page={i + 1}",
                "results": serializer.data,
            }

            cache.set(cache_key, data, timeout=60 * 60 * 24)
            serialized_data_pages.append(data)
            i += 1

        return Response(serialized_data_pages[page_number - 1])

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

        action = inner_doc.actions
        if action.exists():
            action = action.first()
            action.is_removed = True
            action.display = False
            action.save()

        doc_type = get_doc_type_key(doc)
        reset_unified_document_cache(
            document_type=[doc_type, "all"],
            filters=[NEW, UPVOTED, HOT, DISCUSSED, MOST_RSC, EXPIRING_SOON],
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
        action = inner_doc.actions
        if action.exists():
            action = action.first()
            action.is_removed = False
            action.display = True
            action.save()

        doc_type = get_doc_type_key(doc)

        return Response(self.get_serializer(instance=doc).data, status=200)

    def update(self, request, *args, **kwargs):
        update_response = super().update(request, *args, **kwargs)

        hub_ids = list(self.get_object().hubs.values_list("pk", flat=True))
        hub_ids.append(0)

        reset_latest_acitvity_cache(",".join([str(hub_id) for hub_id in hub_ids]))

        doc = self.get_object()
        doc_type = get_doc_type_key(doc)

        return update_response

    def _get_serializer_context(self):
        context = {
            "doc_duds_get_documents": {
                "_include_fields": [
                    "abstract",
                    "created_by",
                    "created_date",
                    "discussion_count",
                    "file",
                    "first_preview",
                    "hot_score",
                    "id",
                    "external_source",
                    "paper_publish_date",
                    "paper_title",
                    "pdf_url",
                    "is_open_access",
                    "oa_status",
                    "pdf_copyright_allows_display",
                    "authors",
                    "preview_img",
                    "renderable_text",
                    "slug",
                    "title",
                    "uploaded_by",
                    "uploaded_date",
                    "citations",
                    "authorships",
                    "work_type",
                ]
            },
            "doc_duds_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "is_locked",
                    "slug",
                    "is_removed",
                    "hub_image",
                    "is_used_for_rep",
                ],
            },
            "pap_dps_get_authorships": {
                "_include_fields": [
                    "id",
                    "author",
                    "author_position",
                    "author_id",
                    "raw_author_name",
                    "is_corresponding",
                ]
            },
            "authorship::get_author": {"_include_fields": ["id", "profile_image"]},
            "doc_dps_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "pap_dps_get_uploaded_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "pap_dps_get_authors": {
                "_include_fields": ["id", "first_name", "last_name"]
            },
            "doc_duds_get_fundraise": {
                "_include_fields": [
                    "id",
                    "status",
                    "goal_amount",
                    "goal_currency",
                    "start_date",
                    "end_date",
                    "amount_raised",
                    "contributors",
                ]
            },
            "pch_dfs_get_contributors": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
        }
        return context

    def _get_featured_documents_queryset(self):
        featured_content = FeaturedContent.objects.all().values_list("unified_document")
        qs = self.get_queryset().filter(id__in=featured_content)
        return qs

    def order_queryset(self, qs, ordering_value):
        from researchhub_document.utils import get_date_ranges_by_time_scope

        time_scope = self.request.query_params.get("time", "today")
        start_date, end_date = get_date_ranges_by_time_scope(time_scope)

        if time_scope not in TIME_SCOPE_CHOICES:
            time_scope = "today"

        ordering = []
        if ordering_value == NEW:
            qs = qs.filter(created_date__range=(start_date, end_date))
            ordering.append("-created_date")
        elif ordering_value == HOT:
            ordering.append("-hot_score_v2")
        elif ordering_value == DISCUSSED:
            key = f"document_filter__discussed_{time_scope}"
            if time_scope != "all":
                qs = qs.filter(
                    document_filter__discussed_date__range=(start_date, end_date),
                    **{f"{key}__gt": 0},
                )
            else:
                qs = qs.filter(document_filter__isnull=False)
            ordering.append(f"-{key}")
        elif ordering_value == UPVOTED:
            if time_scope != "all":
                qs = qs.filter(
                    document_filter__upvoted_date__range=(start_date, end_date)
                )
            else:
                qs = qs.filter(document_filter__isnull=False)
            ordering.append(f"-document_filter__upvoted_{time_scope}")
        elif ordering_value == EXPIRING_SOON:
            ordering.append("document_filter__bounty_expiration_date")
        elif ordering_value == MOST_RSC:
            ordering.append("-document_filter__bounty_total_amount")

        qs = qs.order_by(*ordering)
        return qs

    def _get_unified_document_cache_hit(
        self, document_type, filtering, hub_id, page_number, time_scope
    ):
        cache_hit = None
        if page_number == 1 and hub_id == 0:
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
            "document_filter",
            "document_type",
            "hot_score",
            "hubs",
            "reviews",
            "score",
            "fundraise",
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

        def get_page_url(page_number):
            from urllib.parse import urlencode

            from django.urls import reverse

            if page_number < 1:
                return None

            # Create a mutable copy of the query parameters
            mutable_params = request.query_params.copy()
            mutable_params["page"] = page_number

            # The correct URL pattern based on your router configuration
            base_url = reverse("researchhub_unified_document-get-unified-documents")
            # If that doesn't work, try this alternative:
            # base_url = '/api/researchhub_unified_document/get_unified_documents/'

            return f"{request.build_absolute_uri(base_url)}?{urlencode(mutable_params)}"

        is_anonymous = request.user.is_anonymous
        query_params = request.query_params
        subscribed_hubs = query_params.get("subscribed_hubs", "false").lower() == "true"
        filtering = query_params.get("ordering", HOT)
        time_scope = query_params.get("time", "today")

        if subscribed_hubs and not is_anonymous:
            return self._get_subscribed_unified_documents(request)

        document_request_type = query_params.get("type", "all")
        hub_id = query_params.get("hub_id", 0) or 0
        page_number = int(query_params.get("page", 1))

        # cache_hit = self._get_unified_document_cache_hit(
        #     document_request_type,
        #     filtering,
        #     hub_id,
        #     page_number,
        #     time_scope,
        # )

        # if cache_hit and page_number == 1:
        #     cache_hit = self._cache_hit_with_latest_metadata(cache_hit)
        #     return Response(cache_hit)
        # elif not cache_hit and page_number == 1:
        #     reset_unified_document_cache(
        #         document_type=[document_request_type],
        #         filters=[filtering],
        #         date_ranges=[time_scope],
        #     )

        paginator = UnifiedDocumentPaginator()
        queryset = paginator.build_queryset(
            hub_id=hub_id,
            page_number=page_number,
            initial_queryset=self.filter_queryset(self.get_queryset()),
            sort=filtering,
        )

        PAGE_SIZE = 30
        queryset = self.order_queryset(queryset, filtering)
        offset = (page_number - 1) * PAGE_SIZE
        queryset = queryset[offset : offset + PAGE_SIZE]

        # Materialize the queryset by flushing out the query
        results = list(queryset)

        context = self._get_serializer_context()
        context["hub_id"] = hub_id

        # Don't forget to update the _include_fields in
        # the preload_trending_documents helper function
        # if these _include_fields fields are being updated
        serializer = self.dynamic_serializer_class(
            results,
            _include_fields=[
                "id",
                "created_date",
                "documents",
                "document_filter",
                "document_type",
                "hot_score",
                "hubs",
                "reviews",
                "score",
                "fundraise",
            ],
            many=True,
            context=context,
        )

        response_data = {
            "next": get_page_url(page_number + 1),
            "previous": get_page_url(page_number - 1) if page_number > 1 else None,
            "results": serializer.data,
        }

        return Response(response_data)

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
                "hubs",
                "reviews",
                "score",
                "bounties",
                "fundraise",
            ],
            many=True,
            context=context,
        )
        serializer_data = serializer.data

        return self.get_paginated_response(serializer_data)

    def _cache_hit_with_latest_metadata(self, cache_hit):
        ids = [d["id"] for d in cache_hit["results"]]
        docs_in_cache = ResearchhubUnifiedDocument.all_objects.filter(
            id__in=ids
        ).values("id", "score")
        docs_to_score_map = {d["id"]: d["score"] for d in docs_in_cache}
        for doc in cache_hit["results"]:
            doc["score"] = docs_to_score_map.get(doc["id"])

            if "documents" in doc:
                documents = doc["documents"]
                if isinstance(documents, list) and len(documents) > 0:
                    documents[0]["score"] = docs_to_score_map[doc["id"]]
                elif isinstance(documents, dict):
                    documents["score"] = docs_to_score_map[doc["id"]]
        return cache_hit

    @action(detail=True, methods=["post"], permission_classes=[IsModerator])
    def exclude_from_feed(self, request, pk=None):
        unified_document = self.get_object()
        unified_document.update_filter(FILTER_EXCLUDED_IN_FEED)

        doc_type = get_doc_type_key(unified_document)
        reset_unified_document_cache(
            document_type=["all", doc_type],
            filters=[UPVOTED, HOT, DISCUSSED],
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

        if paper_ids:
            paper_ids = paper_ids.split(",")
        if post_ids:
            post_ids = post_ids.split(",")

        user = request.user
        response = {
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
        return Response(response, status=status.HTTP_200_OK)

    def _get_document_metadata_context(self):
        context = self.get_serializer_context()
        bounties_context_fields = ("id", "amount", "created_by", "status")
        bounties_select_related_fields = ("created_by", "created_by__author_profile")
        discussion_context_fields = ("id", "comment_count", "thread_type")
        purchase_context_fields = ("id", "amount", "user")
        purchase_select_related_fields = ("user", "user__author_profile")
        metadata_context = {
            **context,
            "doc_duds_get_documents": {
                "_include_fields": (
                    "bounties",
                    "discussion_aggregates",
                    "purchases",
                    "user_vote",
                )
            },
            "doc_dps_get_bounties": {"_include_fields": bounties_context_fields},
            "doc_dps_get_bounties_select": bounties_select_related_fields,
            "doc_dps_get_discussions": {"_include_fields": discussion_context_fields},
            "doc_dps_get_discussions_prefetch": ("rh_comments",),
            "doc_dps_get_purchases": {"_include_fields": purchase_context_fields},
            "doc_dps_get_purchases_select": purchase_select_related_fields,
            "pap_dps_get_bounties": {"_include_fields": bounties_context_fields},
            "pap_dps_get_bounties_select": bounties_select_related_fields,
            "pap_dps_get_discussions": {"_include_fields": discussion_context_fields},
            "pap_dps_get_discussions_prefetch": ("rh_comments",),
            "pap_dps_get_purchases": {"_include_fields": purchase_context_fields},
            "pch_dps_get_user": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
            "rep_dbs_get_created_by": {"_include_fields": ("author_profile", "id")},
            "usr_dus_get_author_profile": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                ]
            },
            "doc_duds_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "slug",
                    "created_date",
                    "is_used_for_rep",
                ]
            },
            "doc_duds_get_fundraise": {
                "_include_fields": [
                    "id",
                    "status",
                    "goal_amount",
                    "goal_currency",
                    "start_date",
                    "end_date",
                    "amount_raised",
                    "contributors",
                ]
            },
            "pch_dfs_get_contributors": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
        }

        return metadata_context

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def get_document_metadata(self, request, pk=None):
        unified_document = self.get_object()
        metadata_context = self._get_document_metadata_context()

        serializer = self.dynamic_serializer_class(
            unified_document,
            _include_fields=(
                "id",
                "documents",
                "reviews",
                "score",
                "hubs",
                "fundraise",
            ),
            context=metadata_context,
        )
        serializer_data = serializer.data

        return Response(serializer_data, status=status.HTTP_200_OK)


def get_user_votes(created_by, doc_ids, reaction_content_type):
    return GrmVote.objects.filter(
        content_type=reaction_content_type, object_id__in=doc_ids, created_by=created_by
    )
