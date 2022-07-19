import base64
import json
from urllib.parse import urlparse

import requests
from django.contrib.admin.options import get_content_type_for_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import URLValidator
from django.db import IntegrityError
from django.db.models import Count, F, IntegerField, Prefetch, Q, Sum, Value
from django.db.models.functions import Cast, Coalesce
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from elasticsearch.exceptions import ConnectionError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response

from discussion.models import Vote as GrmVote
from discussion.reaction_serializers import FlagSerializer as GrmFlagSerializer
from discussion.reaction_serializers import VoteSerializer as GrmVoteSerializer
from discussion.reaction_views import ReactionViewActionMixin, create_flag
from google_analytics.signals import get_event_hit_response
from paper.exceptions import PaperSerializerError
from paper.filters import PaperFilter
from paper.models import AdditionalFile, Figure, Flag, Paper, PaperSubmission
from paper.permissions import (
    CreatePaper,
    IsAuthor,
    IsModeratorOrVerifiedAuthor,
    UpdateOrDeleteAdditionalFile,
    UpdatePaper,
)
from paper.serializers import (
    AdditionalFileSerializer,
    BookmarkSerializer,
    DynamicPaperSerializer,
    FigureSerializer,
    PaperReferenceSerializer,
    PaperSerializer,
    PaperSubmissionSerializer,
)
from paper.tasks import celery_process_paper, censored_paper_cleanup
from paper.utils import (
    add_default_hub,
    clean_abstract,
    get_cache_key,
    get_csl_item,
    get_pdf_location_for_csl_item,
)
from purchase.models import Purchase
from reputation.models import Contribution
from reputation.tasks import create_contribution
from researchhub.lib import get_document_id_from_path
from researchhub_document.permissions import HasDocumentCensorPermission
from researchhub_document.related_models.constants.filters import (
    DISCUSSED,
    NEWEST,
    OPEN_ACCESS,
    TOP,
    TRENDING,
)
from researchhub_document.utils import reset_unified_document_cache
from utils.http import GET, POST, check_url_contains_pdf
from utils.permissions import CreateOnly, CreateOrUpdateIfAllowed, HasAPIKey
from utils.sentry import log_error, log_info
from utils.siftscience import decisions_api, events_api
from utils.throttles import THROTTLE_CLASSES


class PaperViewSet(viewsets.ModelViewSet, ReactionViewActionMixin):
    queryset = Paper.objects.filter()
    serializer_class = PaperSerializer
    dynamic_serializer_class = DynamicPaperSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    search_fields = ("title", "doi", "paper_title")
    filter_class = PaperFilter
    throttle_classes = THROTTLE_CLASSES
    ordering = "-created_date"

    permission_classes = [
        (IsAuthenticatedOrReadOnly | HasAPIKey)
        & CreatePaper
        & UpdatePaper
        & CreateOrUpdateIfAllowed
    ]

    # NOTE: calvinhle - manually overriding default get_object
    # self.get_queryset() was causing error, presumabily from GenericRelation problem
    # need to get back to this after full migrations
    def get_object(self):
        queryset = self.filter_queryset(self.queryset)

        # Perform the lookup filtering.
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field

        assert lookup_url_kwarg in self.kwargs, (
            "Expected view %s to be called with a URL keyword argument "
            'named "%s". Fix your URL conf, or set the `.lookup_field` '
            "attribute on the view correctly."
            % (self.__class__.__name__, lookup_url_kwarg)
        )

        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        obj = get_object_or_404(queryset, **filter_kwargs)

        # May raise a permission denied
        self.check_object_permissions(self.request, obj)

        return obj

    def prefetch_lookups(self):
        return (
            "uploaded_by",
            "uploaded_by__bookmarks",
            "uploaded_by__author_profile",
            "uploaded_by__author_profile__user",
            "uploaded_by__subscribed_hubs",
            "authors",
            "authors__user",
            # Prefetch(
            #     'bullet_points',
            #     queryset=BulletPoint.objects.filter(
            #         is_head=True,
            #         is_removed=False,
            #         ordinal__isnull=False
            #     ).order_by('ordinal')
            # ),
            # 'summary',
            # 'summary__previous',
            # 'summary__proposed_by__bookmarks',
            # 'summary__proposed_by__subscribed_hubs',
            # 'summary__proposed_by__author_profile',
            # 'summary__paper',
            "moderators",
            "hubs",
            "hubs__subscribers",
            "votes",
            "flags",
            "purchases",
            "threads",
            "threads__comments",
            Prefetch(
                "figures",
                queryset=Figure.objects.filter(figure_type=Figure.FIGURE).order_by(
                    "created_date"
                ),
                to_attr="figure_list",
            ),
            Prefetch(
                "figures",
                queryset=Figure.objects.filter(figure_type=Figure.PREVIEW).order_by(
                    "created_date"
                ),
                to_attr="preview_list",
            ),
        )

    def get_queryset(self, prefetch=True, include_autopull=False):
        query_params = self.request.query_params
        queryset = self.queryset
        ordering = query_params.get("ordering", None)
        external_source = query_params.get("external_source", False)
        # queryset = queryset.filter(pdf_license__isnull=False)

        if (
            query_params.get("make_public")
            or query_params.get("all")
            or (ordering and "removed" in ordering)
        ):
            pass
        else:
            queryset = queryset.filter(is_removed=False)

        # if ordering == 'newest' and not include_autopull:
        #     queryset = queryset.filter(uploaded_by__isnull=False)

        user = self.request.user
        if user.is_staff:
            return queryset

        if not user.is_anonymous and user.moderator and external_source:
            queryset = queryset.filter(
                is_removed=False, retrieved_from_external_source=True
            )
        if prefetch:
            return queryset.prefetch_related(*self.prefetch_lookups())
        else:
            return queryset

    def create(self, request, *args, **kwargs):
        try:
            doi = request.data.get("doi", "")
            duplicate_papers = Paper.objects.filter(doi=doi)
            if duplicate_papers:
                serializer = DynamicPaperSerializer(
                    duplicate_papers[:1],
                    _include_fields=["doi", "id", "title", "url"],
                    many=True,
                )
                duplicate_data = {"data": serializer.data}
                return Response(duplicate_data, status=status.HTTP_403_FORBIDDEN)
            response = super().create(request, *args, **kwargs)
            return response
        except IntegrityError as e:
            return self._get_integrity_error_response(e)
        except PaperSerializerError as e:
            print("EXCEPTION: ", e)
            return Response(str(e), status=status.HTTP_400_BAD_REQUEST)

    def _get_integrity_error_response(self, error):
        error_message = str(error)
        parts = error_message.split("DETAIL:")
        try:
            error_message = parts[1].strip()
            if "url" in error_message:
                error_message = "A paper with this url already exists."
            if "doi" in error_message:
                error_message = "A paper with this DOI already exists."
            if "DOI" in error_message:
                error_message = "Invalid DOI"
        except IndexError:
            error_message = "A paper with this url or DOI already exists."
        return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

    def _get_paper_context(self, request=None):
        context = {
            "request": request,
            "doc_duds_get_documents": {"_include_fields": ["id"]},
            "pap_dps_get_unified_document": {
                "_include_fields": [
                    "id",
                    "reviews",
                    "is_removed",
                    "document_type",
                    "documents",
                ]
            },
            "pap_dps_get_user_vote": {},
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
        }
        return context

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()

        context = self._get_paper_context(request)
        cache_key = get_cache_key("paper", instance.id)
        cache_hit = cache.get(cache_key)
        if cache_hit is not None:
            vote = self.dynamic_serializer_class(context=context).get_user_vote(
                instance
            )
            cache_hit["user_vote"] = vote
            return Response(cache_hit)

        serializer = self.dynamic_serializer_class(
            instance,
            context=context,
            _include_fields=[
                "authors",
                "boost_amount",
                "bounties",
                "id",
                "file",
                "first_preview",
                "hubs",
                "score",
                "uploaded_by",
                "uploaded_date",
                "discussion_count",
                "pdf_file_extract",
                "is_open_access",
                "external_source",
                "title",
                "doi",
                "paper_title",
                "paper_publish_date",
                "raw_authors",
                "abstract",
                "url",
                "pdf_url",
                "pdf_license",
                "slug",
                "unified_document",
                "uploaded_date",
                "created_date",
            ],
        )
        serializer_data = serializer.data

        cache.set(cache_key, serializer_data, timeout=60 * 60 * 24 * 7)
        return Response(serializer_data)

    def list(self, request, *args, **kwargs):
        default_pagination_class = self.pagination_class
        if request.query_params.get("limit"):
            self.pagination_class = LimitOffsetPagination
        else:
            self.pagination_class = default_pagination_class
        return super().list(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()

        # TODO: This needs improvement so we guarantee that we are tracking
        # file created location when a file is actually being added and not
        # just any updates to the paper
        created_location = None
        if request.query_params.get("created_location") == "progress":
            created_location = Paper.CREATED_LOCATION_PROGRESS
            request.data["file_created_location"] = created_location

        response = super().update(request, *args, **kwargs)

        if (created_location is not None) and not request.user.is_anonymous:
            instance = self.get_object()
            self._send_created_location_ga_event(instance, request.user)

        instance.reset_cache(use_celery=False)
        return response

    def _send_created_location_ga_event(self, instance, user):
        created = True
        category = "Paper"
        label = "Pdf from Progress"
        action = "Upload"
        user_id = user.id
        paper_id = instance.id
        date = instance.updated_date

        return get_event_hit_response(
            instance,
            created,
            category,
            label,
            action=action,
            user_id=user_id,
            paper_id=paper_id,
            date=date,
        )

    @action(
        detail=True,
        methods=["put", "patch", "delete"],
        permission_classes=[HasDocumentCensorPermission],
    )
    def censor(self, request, pk=None):
        paper = self.get_object()
        paper_id = paper.id
        unified_doc = paper.unified_document
        cache_key = get_cache_key("paper", paper_id)
        cache.delete(cache_key)
        hub_ids = list(paper.hubs.values_list("id", flat=True))

        content_id = f"{type(paper).__name__}_{paper_id}"
        user = request.user
        content_creator = paper.uploaded_by
        if content_creator:
            events_api.track_flag_content(content_creator, content_id, user.id)
            decisions_api.apply_bad_content_decision(
                content_creator, content_id, "MANUAL_REVIEW", user
            )
            decisions_api.apply_bad_user_decision(
                content_creator, "MANUAL_REVIEW", user
            )

        Contribution.objects.filter(unified_document=unified_doc).delete()
        paper.is_removed = True
        paper.save()
        censored_paper_cleanup.apply_async((paper_id,), priority=3)

        unified_document = paper.unified_document
        unified_document.is_removed = True
        unified_document.save()

        reset_unified_document_cache(
            hub_ids,
            filters=[TRENDING, TOP, DISCUSSED, NEWEST, OPEN_ACCESS],
            document_type=["all", "paper"],
            with_default_hub=True,
        )

        return Response("Paper was deleted.", status=200)

    @action(
        detail=True,
        methods=["put", "patch", "delete"],
        permission_classes=[HasDocumentCensorPermission],
    )
    def restore_paper(self, request, pk=None):
        paper = None
        try:
            paper = self.get_object()
        except Exception:
            paper = Paper.objects.get(id=request.data["id"])
            pass
        paper.is_removed = False
        paper.save()
        paper.reset_cache(use_celery=False)

        hub_ids = paper.hubs.values_list("id", flat=True)
        reset_unified_document_cache(
            hub_ids,
            filters=[TRENDING, TOP, DISCUSSED, NEWEST, OPEN_ACCESS],
            document_type=["all", "paper"],
        )
        return Response(self.get_serializer(instance=paper).data, status=200)

    @action(
        detail=True,
        methods=["put", "patch", "delete"],
        permission_classes=[HasDocumentCensorPermission],
    )
    def censor_pdf(self, request, pk=None):
        paper = self.get_object()
        paper_id = paper.id
        paper.file = None
        paper.url = None
        paper.pdf_url = None
        paper.figures.all().delete()
        paper.save()

        content_id = f"{type(paper).__name__}_{paper_id}"
        user = request.user
        content_creator = paper.uploaded_by
        events_api.track_flag_content(content_creator, content_id, user.id)
        decisions_api.apply_bad_content_decision(
            content_creator, content_id, "MANUAL_REVIEW", user
        )
        decisions_api.apply_bad_user_decision(content_creator, "MANUAL_REVIEW", user)

        hub_ids = list(paper.hubs.values_list("id", flat=True))
        hub_ids = add_default_hub(hub_ids)

        paper.reset_cache(use_celery=False)
        return Response(self.get_serializer(instance=paper).data, status=200)

    @action(
        detail=True, methods=["post", "put", "patch"], permission_classes=[IsAuthor]
    )
    def assign_moderator(self, request, pk=None):
        """Assign users as paper moderators"""
        paper = self.get_object()
        moderators = request.data.get("moderators")
        if not isinstance(moderators, list):
            moderators = [moderators]
        paper.moderators.add(*moderators)
        paper.save()
        return Response(PaperSerializer(paper).data)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticatedOrReadOnly & CreateOrUpdateIfAllowed],
    )
    def bookmark(self, request, pk=None):
        paper = self.get_object()
        user = request.user

        if paper in user.bookmarks.all():
            return Response("Bookmark already added", status=400)
        else:
            user.bookmarks.add(paper)
            user.save()
            serialized = BookmarkSerializer(
                {"user": user.id, "bookmarks": user.bookmarks.all()}
            )
            return Response(serialized.data, status=201)

    @bookmark.mapping.delete
    def delete_bookmark(self, request, pk=None):
        paper = self.get_object()
        user = request.user

        try:
            user.bookmarks.remove(paper)
            user.save()
            return Response(paper.id, status=200)
        except Exception as e:
            print(e)
            return Response(f"Failed to remove {paper.id} from bookmarks", status=400)

    @action(detail=True, methods=[GET])
    def referenced_by(self, request, pk=None):
        paper = self.get_object()
        queryset = paper.referenced_by.all()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = PaperReferenceSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=[GET])
    def references(self, request, pk=None):
        paper = self.get_object()
        queryset = paper.references.all()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = PaperReferenceSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def user_vote(self, request, pk=None):
        paper = self.get_object()
        user = request.user
        vote = retrieve_vote(user, paper)
        return get_vote_response(vote, 200)

    @user_vote.mapping.delete
    def delete_user_vote(self, request, pk=None):
        try:
            paper = self.get_object()
            user = request.user
            vote = retrieve_vote(user, paper)
            vote_id = vote.id
            vote.delete()
            return Response(vote_id, status=200)
        except Exception as e:
            return Response(f"Failed to delete vote: {e}", status=400)

    @action(
        detail=False,
        methods=["get"],
    )
    def check_user_vote(self, request):
        paper_ids = request.query_params["paper_ids"].split(",")
        user = request.user
        response = {}

        if user.is_authenticated:
            votes = GrmVote.objects.filter(
                content_type=get_content_type_for_model(Paper),
                object_id__in=paper_ids,
                created_by=user,
            )

            for vote in votes.iterator():
                paper_id = vote.object_id
                data = GrmVoteSerializer(instance=vote).data
                response[paper_id] = data

        return Response(response, status=status.HTTP_200_OK)

    @action(detail=False, methods=[POST])
    def check_url(self, request):
        url = request.data.get("url", None)
        url_is_pdf = check_url_contains_pdf(url)
        data = {"found_file": url_is_pdf}
        return Response(data, status=status.HTTP_200_OK)

    @staticmethod
    def search_by_csl_item(csl_item):
        """
        Perform an elasticsearch query for papers matching
        the input CSL_Item.
        """
        from elasticsearch_dsl import Q, Search

        search = Search(index="paper")
        title = csl_item.get("title", "")
        query = Q("match", title=title) | Q("match", paper_title=title)
        if csl_item.get("DOI"):
            query |= Q("match", doi=csl_item["DOI"])
        search.query(query)
        return search

    @action(detail=False, methods=["post"])
    def search_by_url(self, request):
        # TODO: Ensure we are saving data from here, license, title,
        # publish date, authors, pdf
        # handle pdf url, journal url, or pdf upload
        # TODO: Refactor
        """
        Retrieve bibliographic metadata and potential paper matches
        from the database for `url` (specified via request post data).
        """
        url = request.data.get("url").strip()
        data = {"url": url}

        if not url:
            return Response(
                "search_by_url requests must specify 'url'",
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            URLValidator()(url)
        except (ValidationError, Exception) as e:
            print(e)
            return Response(
                f"Double check that URL is valid: {url}",
                status=status.HTTP_400_BAD_REQUEST,
            )

        url_is_pdf = check_url_contains_pdf(url)
        data["url_is_pdf"] = url_is_pdf

        duplicate_papers = Paper.objects.filter(
            Q(url__icontains=url) | Q(pdf_url__icontains=url)
        )
        if duplicate_papers.exists():
            duplicate_paper = duplicate_papers.first()
            serializer_data = self.serializer_class(
                duplicate_paper, context={"purchase_minimal_serialization": True}
            ).data
            data = {"key": "url", "results": serializer_data}
            return Response(data, status=status.HTTP_403_FORBIDDEN)

        try:
            csl_item = get_csl_item(url)
        except Exception as error:
            data["warning"] = f"Generating csl_item failed with:\n{error}"
            log_error(error)
            csl_item = None

        if csl_item:
            # Cleaning csl data
            cleaned_title = csl_item.get("title", "").strip()
            csl_item["title"] = cleaned_title
            abstract = csl_item.get("abstract", "")
            cleaned_abstract = clean_abstract(abstract)
            csl_item["abstract"] = cleaned_abstract

            url_is_unsupported_pdf = url_is_pdf and csl_item.get("URL") == url
            data["url_is_unsupported_pdf"] = url_is_unsupported_pdf
            csl_item.url_is_unsupported_pdf = url_is_unsupported_pdf
            data["csl_item"] = csl_item
            data["oa_pdf_location"] = get_pdf_location_for_csl_item(csl_item)
            doi = csl_item.get("DOI", None)

            duplicate_papers = Paper.objects.exclude(doi=None).filter(doi=doi)
            if duplicate_papers.exists():
                duplicate_paper = duplicate_papers.first()
                serializer_data = self.serializer_class(
                    duplicate_paper, context={"purchase_minimal_serialization": True}
                ).data
                data = {"key": "doi", "results": serializer_data}
                return Response(data, status=status.HTTP_403_FORBIDDEN)

            data["paper_publish_date"] = csl_item.get_date("issued", fill=True)

        if csl_item and request.data.get("search", False):
            # search existing papers
            search = self.search_by_csl_item(csl_item)
            try:
                search = search.execute()
            except ConnectionError:
                return Response(
                    "Search failed due to an elasticsearch ConnectionError.",
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            data["search"] = [hit.to_dict() for hit in search.hits]

        return Response(data, status=status.HTTP_200_OK)

    def calculate_paper_ordering(self, papers, ordering, start_date, end_date):
        if "hot_score" in ordering:
            order_papers = papers.order_by(ordering)
        elif "score" in ordering:
            boost_amount = Coalesce(
                Sum(
                    Cast("purchases__amount", output_field=IntegerField()),
                    filter=Q(
                        purchases__paid_status=Purchase.PAID,
                        purchases__user__moderator=True,
                        purchases__amount__gt=0,
                        purchases__boost_time__gt=0,
                    ),
                ),
                Value(0),
            )
            order_papers = (
                papers.filter(
                    created_date__range=[start_date, end_date],
                )
                .annotate(total_score=boost_amount + F("score"))
                .order_by("-total_score")
            )
        elif "discussed" in ordering:
            threads_count = Count("threads")
            comments_count = Count("threads__comments")

            order_papers = (
                papers.filter(
                    Q(threads__source="researchhub")
                    | Q(threads__comments__source="researchhub"),
                    Q(threads__created_date__range=[start_date, end_date])
                    | Q(threads__comments__created_date__range=[start_date, end_date]),
                )
                .annotate(
                    discussed=threads_count + comments_count,
                    discussed_secondary=F("discussion_count"),
                )
                .order_by(ordering, ordering + "_secondary")
            )
        elif "removed" in ordering:
            order_papers = papers.order_by("-created_date")
        elif "twitter_score" in ordering:
            order_papers = papers.order_by("-twitter_score")
        elif "user-uploaded" in ordering:
            order_papers = papers.filter(created_date__gte=start_date).order_by(
                "-created_date"
            )
        else:
            order_papers = papers.order_by(ordering)

        return order_papers

    @action(
        detail=True, methods=["get"], permission_classes=[IsAuthenticatedOrReadOnly]
    )
    def pdf_extract(self, request, pk=None):
        paper = Paper.objects.get(id=pk)
        pdf_file = paper.pdf_file_extract
        edited_file = paper.edited_file_extract

        external_source = paper.external_source
        if (
            external_source and external_source.lower() == "arxiv"
        ) or "arxiv" in paper.alternate_ids:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if not pdf_file.name:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if edited_file.name:
            edited_json = json.loads(edited_file.read())
            return Response(edited_json, status=status.HTTP_200_OK)

        html_bytes = paper.pdf_file_extract.read()
        b64_string = base64.b64encode(html_bytes)
        return Response(b64_string, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], permission_classes=[AllowAny])
    def edit_file_extract(self, request, pk=None):
        paper = self.get_object()
        data = request.data
        filename = f"{paper.id}.json"
        paper.edited_file_extract.save(
            filename, ContentFile(json.dumps(data).encode("utf8"))
        )
        return Response(status=status.HTTP_200_OK)

    def _set_hub_paper_ordering(self, request):
        ordering = request.query_params.get("ordering", None)
        # TODO send correct ordering from frontend
        if ordering == "removed":
            ordering = "removed"
        elif ordering == "top_rated":
            ordering = "-score"
        elif ordering == "most_discussed":
            ordering = "-discussed"
        elif ordering == "newest":
            ordering = "-created_date"
        elif ordering == "hot":
            ordering = "-hot_score"
        elif ordering == "user-uploaded":
            ordering = "user-uploaded"
        else:
            ordering = "-score"
        return ordering

    def _get_filtered_papers(self, hub_id, ordering):
        # hub_id = 0 is the homepage
        # we aren't on a specific hub so don't filter by that hub_id
        if int(hub_id) == 0:
            qs = self.get_queryset(
                prefetch=False,
            ).prefetch_related(*self.prefetch_lookups())

            if "removed" in ordering:
                qs = qs.filter(is_removed=True)
            elif "user-uploaded" in ordering:
                qs = qs.filter(uploaded_by_id__isnull=False)
            else:
                qs = qs.filter(
                    is_removed=False,
                    is_removed_by_user=False,
                )
        else:
            qs = (
                self.get_queryset(prefetch=False)
                .filter(
                    hubs__id__in=[int(hub_id)],
                )
                .prefetch_related(*self.prefetch_lookups())
            )

            if "removed" in ordering:
                qs = qs.filter(is_removed=True)
            elif "user-uploaded" in ordering:
                qs = qs.filter(uploaded_by_id__isnull=False)
            else:
                qs = qs.filter(
                    is_removed=False,
                    is_removed_by_user=False,
                )
        return qs


class AdditionalFileViewSet(viewsets.ModelViewSet):
    queryset = AdditionalFile.objects.all()
    serializer_class = AdditionalFileSerializer
    throttle_classes = THROTTLE_CLASSES
    permission_classes = [IsAuthenticatedOrReadOnly & UpdateOrDeleteAdditionalFile]

    def get_queryset(self):
        queryset = super().get_queryset()
        paper_id = get_document_id_from_path(self.request)
        if paper_id is not None:
            queryset = queryset.filter(paper=paper_id)
        return queryset


class FigureViewSet(viewsets.ModelViewSet):
    queryset = Figure.objects.all()
    serializer_class = FigureSerializer
    throttle_classes = THROTTLE_CLASSES

    permission_classes = [IsModeratorOrVerifiedAuthor]

    def get_queryset(self):
        return self.queryset

    def get_figures(self, paper_id, figure_type=None):
        # Returns all figures
        paper = Paper.objects.get(id=paper_id)
        figures = self.get_queryset().filter(paper=paper)

        if figure_type:
            figures = figures.filter(figure_type=figure_type)

        figures = figures.order_by("-figure_type", "created_date")
        figure_serializer = self.serializer_class(figures, many=True)
        return figure_serializer.data

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthor & CreateOrUpdateIfAllowed],
    )
    def add_figure(self, request, pk=None):
        user = request.user
        if user.is_anonymous:
            user = None

        created_location = None
        if request.query_params.get("created_location") == "progress":
            created_location = Figure.CREATED_LOCATION_PROGRESS

        paper = Paper.objects.get(id=pk)
        figures = request.FILES.values()
        figure_type = request.data.get("figure_type")
        urls = []
        try:
            for figure in figures:
                fig = Figure.objects.create(
                    paper=paper,
                    file=figure,
                    figure_type=figure_type,
                    created_by=user,
                    created_location=created_location,
                )
                urls.append({"id": fig.id, "file": fig.file.url})
            return Response({"files": urls}, status=200)
        except Exception as e:
            log_error(e)
            return Response(status=500)

    @action(
        detail=True,
        methods=["delete"],
        permission_classes=[IsAuthor & CreateOrUpdateIfAllowed],
    )
    def delete_figure(self, request, pk=None):
        figure = self.get_queryset().get(id=pk)
        figure.delete()
        return Response(status=200)

    @action(
        detail=True, methods=["get"], permission_classes=[IsAuthenticatedOrReadOnly]
    )
    def get_all_figures(self, request, pk=None):
        cache_key = get_cache_key("figure", pk)
        cache_hit = cache.get(cache_key)
        if cache_hit is not None:
            return Response({"data": cache_hit}, status=status.HTTP_200_OK)

        serializer_data = self.get_figures(pk)
        cache.set(cache_key, serializer_data, timeout=60 * 60 * 24 * 7)
        return Response({"data": serializer_data}, status=status.HTTP_200_OK)

    @action(
        detail=True, methods=["get"], permission_classes=[IsAuthenticatedOrReadOnly]
    )
    def get_preview_figures(self, request, pk=None):
        # Returns pdf preview figures
        serializer_data = self.get_figures(pk, figure_type=Figure.PREVIEW)
        return Response({"data": serializer_data}, status=status.HTTP_200_OK)

    @action(
        detail=True, methods=["get"], permission_classes=[IsAuthenticatedOrReadOnly]
    )
    def get_regular_figures(self, request, pk=None):
        # Returns regular figures
        serializer_data = self.get_figures(pk, figure_type=Figure.FIGURE)
        return Response({"data": serializer_data}, status=status.HTTP_200_OK)


def find_vote(user, paper, vote_type):
    vote = GrmVote.objects.filter(
        content_type=get_content_type_for_model(paper),
        created_by=user,
        object_id=paper.id,
        vote_type=vote_type,
    )
    if vote:
        return True
    return False


def get_vote_response(vote, status_code):
    """Returns Response with serialized `vote` data and `status_code`."""
    serializer = GrmVoteSerializer(vote)
    return Response(serializer.data, status=status_code)


def retrieve_vote(user, paper):
    try:
        return GrmVote.objects.get(
            content_type=get_content_type_for_model(paper),
            created_by=user,
            object_id=paper.id,
        )
    except GrmVote.DoesNotExist:
        return None


class PaperSubmissionViewSet(viewsets.ModelViewSet):
    queryset = PaperSubmission.objects.all()
    serializer_class = PaperSubmissionSerializer
    throttle_classes = THROTTLE_CLASSES
    permission_classes = [IsAuthenticated | HasAPIKey, CreateOnly]

    def create(self, *args, **kwargs):
        data = self.request.data
        url = data.get("url", "")

        # Appends http if protocol does not exist
        parsed_url = urlparse(url)
        if not parsed_url.scheme:
            url = f"http://{parsed_url.geturl()}"
            data["url"] = url

        duplicate_papers = Paper.objects.filter(
            Q(url__icontains=url) | Q(pdf_url__icontains=url)
        )
        if duplicate_papers:
            serializer = DynamicPaperSerializer(
                duplicate_papers,
                _include_fields=["doi", "id", "title", "url"],
                many=True,
            )
            duplicate_data = {"data": serializer.data}
            return Response(duplicate_data, status=status.HTTP_403_FORBIDDEN)

        data["uploaded_by"] = self.request.user.id
        response = super().create(*args, **kwargs)
        if response.status_code == 201:
            data = response.data
            celery_process_paper.apply_async(
                (data["id"],),
                priority=1,
                countdown=3,
            )
        return response

    @action(detail=False, methods=["post"])
    def create_from_doi(self, request):
        data = request.data
        # TODO: Sanitize?
        doi = data.get("doi", None)

        # DOI validity check
        doi_url = urlparse(doi)
        doi_res = requests.post(
            "https://dx.doi.org/", data={"hdl": doi}, allow_redirects=False, timeout=5
        )
        invalid_doi_res = Response(
            {"data": "Invalid DOI - Ensure it is in the form of '10.1000/abc123'"},
            status=status.HTTP_404_NOT_FOUND,
        )
        if doi_url.scheme or "doi.org" in doi:
            # Avoiding data that comes in as a url or as a DOI url
            return invalid_doi_res
        elif doi_res.status_code == status.HTTP_404_NOT_FOUND:
            return invalid_doi_res

        # Duplicate DOI check
        duplicate_papers = Paper.objects.filter(doi__contains=doi)
        if duplicate_papers:
            serializer = DynamicPaperSerializer(
                duplicate_papers,
                _include_fields=["doi", "id", "title", "url"],
                many=True,
            )
            duplicate_data = {"data": serializer.data}
            return Response(duplicate_data, status=status.HTTP_403_FORBIDDEN)

        data["uploaded_by"] = request.user.id
        response = super().create(request)
        if response.status_code == 201:
            data = response.data
            celery_process_paper.apply_async(
                (data["id"],),
                priority=1,
                countdown=3,
            )
        return response
