import base64
import json
from urllib.parse import urlparse

import requests
from django.contrib.admin.options import get_content_type_for_model
from django.contrib.postgres.search import SearchQuery
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.db.models import Count, F, IntegerField, Q, Sum, Value
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from elasticsearch.exceptions import ConnectionError
from elasticsearch_dsl import Search
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from analytics.amplitude import track_event
from discussion.models import Vote as GrmVote
from discussion.reaction_serializers import VoteSerializer as GrmVoteSerializer
from discussion.reaction_views import ReactionViewActionMixin
from google_analytics.signals import get_event_hit_response
from paper.exceptions import DOINotFoundError, PaperSerializerError
from paper.filters import PaperFilter
from paper.models import Figure, Paper, PaperSubmission, PaperVersion
from paper.paper_upload_tasks import celery_process_paper
from paper.permissions import CreatePaper, IsAuthor, UpdatePaper
from paper.related_models.authorship_model import Authorship
from paper.related_models.series_model import PaperSeries, PaperSeriesDeclaration
from paper.serializers import (
    DynamicPaperSerializer,
    FigureSerializer,
    PaperReferenceSerializer,
    PaperSerializer,
    PaperSubmissionSerializer,
)
from paper.tasks import censored_paper_cleanup
from paper.utils import (
    clean_abstract,
    get_cache_key,
    get_csl_item,
    get_pdf_location_for_csl_item,
)
from purchase.models import Purchase
from reputation.models import Contribution
from reputation.related_models.paper_reward import (
    OPEN_ACCESS_MULTIPLIER,
    OPEN_DATA_MULTIPLIER,
    PREREGISTERED_MULTIPLIER,
)
from researchhub.permissions import IsObjectOwnerOrModerator
from researchhub_document.permissions import HasDocumentCensorPermission
from search.documents.paper import PaperDocument
from user.related_models.author_model import Author
from utils.doi import DOI
from utils.http import GET, POST, check_url_contains_pdf
from utils.openalex import OpenAlex
from utils.permissions import CreateOrUpdateIfAllowed, HasAPIKey, PostOnly
from utils.sentry import log_error
from utils.siftscience import SIFT_PAPER, decisions_api, events_api, sift_track
from utils.throttles import THROTTLE_CLASSES


class PaperViewSet(ReactionViewActionMixin, viewsets.ModelViewSet):
    queryset = Paper.objects.all()
    serializer_class = PaperSerializer
    dynamic_serializer_class = DynamicPaperSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    search_fields = ("title", "doi", "paper_title")
    filterset_class = PaperFilter
    throttle_classes = THROTTLE_CLASSES
    ordering = "-created_date"

    permission_classes = [
        (IsAuthenticatedOrReadOnly | HasAPIKey)
        & CreatePaper
        & UpdatePaper
        & CreateOrUpdateIfAllowed
    ]

    def prefetch_lookups(self):
        return (
            "uploaded_by",
            "uploaded_by__author_profile",
            "uploaded_by__author_profile__user",
            "uploaded_by__subscribed_hubs",
            "authors",
            "authors__user",
            "moderators",
            "hubs",
            "hubs__subscribers",
            "votes",
            "flags",
            "peer_reviews",
            "purchases",
            "threads",
            "threads__comments",
            "figures",
        )

    def get_queryset(self, prefetch=True):
        query_params = self.request.query_params
        queryset = self.queryset
        ordering = query_params.get("ordering", None)
        external_source = query_params.get("external_source", False)

        if (
            query_params.get("make_public")
            or query_params.get("all")
            or (ordering and "removed" in ordering)
        ):
            pass
        else:
            queryset = queryset.filter(is_removed=False)

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

    @track_event
    @sift_track(SIFT_PAPER)
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

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[IsAuthenticated & CreatePaper],
    )
    def create_researchhub_paper(self, request):
        """
        Create a paper with associated hubs and authors in a single request.

        Fields:
        - abstract: string
        - authors: list[dict] - Each dict contains:
            - id: int (author ID)
            - author_position: string ("first", "middle", or "last")
            - department: string
            - email: string (optional)
            - institution_id: int (optional)
            - is_corresponding: boolean
        - change_description: string (optional)
        - hub_ids: list[int]
        - pdf_url: string
        - previous_paper_id: int (optional)
        - title: string
        - declarations: list[dict] - Each dict contains:
            - declaration_type: string
                - options: ACCEPT_TERMS_AND_CONDITIONS, AUTHORIZE_CC_BY_4_0, CONFIRM_AUTHORS_RIGHTS, CONFIRM_ORIGINALITY_AND_COMPLIANCE
            - accepted: boolean
        """
        try:
            with transaction.atomic():
                # Extract data from request
                abstract = request.data.get("abstract")
                authors_data = request.data.get("authors", [])
                change_description = request.data.get("change_description")
                hub_ids = request.data.get("hub_ids", [])
                pdf_url = request.data.get("pdf_url")
                previous_paper_id = request.data.get("previous_paper_id")
                title = request.data.get("title")
                declarations = request.data.get("declarations", [])

                previous_paper = None
                if previous_paper_id:
                    try:
                        previous_paper = Paper.objects.get(id=previous_paper_id)
                    except Paper.DoesNotExist:
                        return Response(
                            {"error": "Previous paper not found"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                if not title or not abstract:
                    return Response(
                        {"error": "Title and abstract are required"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Validate author data
                if not authors_data:
                    return Response(
                        {"error": "At least one author is required"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Check for at least one corresponding author
                if not any(
                    author.get("is_corresponding", False) for author in authors_data
                ):
                    return Response(
                        {"error": "At least one corresponding author is required"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Create paper
                paper_data = {
                    "title": title,
                    "paper_title": title,
                    "abstract": abstract,
                    "uploaded_by": request.user,
                    "paper_publish_date": timezone.now(),
                    "pdf_license": "cc-by-nc-4.0",
                    "work_type": "preprint",
                }

                if pdf_url:
                    paper_data["pdf_url"] = pdf_url

                paper = Paper.objects.create(**paper_data)

                # Create paper series
                paper_series = PaperSeries.objects.create()

                # Get valid declaration types
                valid_declaration_types = dict(
                    PaperSeriesDeclaration.DECLARATION_TYPE_CHOICES
                ).keys()

                # Check for missing declarations
                missing_declarations = [
                    d_type
                    for d_type in valid_declaration_types
                    if not any(d["declaration_type"] == d_type for d in declarations)
                ]
                if missing_declarations:
                    return Response(
                        {
                            "error": f"Missing required declarations: {', '.join(missing_declarations)}"
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Check for unaccepted declarations
                unaccepted_declarations = [
                    d["declaration_type"]
                    for d in declarations
                    if d["declaration_type"] in valid_declaration_types
                    and not d.get("accepted", False)
                ]
                if unaccepted_declarations:
                    return Response(
                        {
                            "error": f"All declarations must be accepted. Unaccepted declarations: {', '.join(unaccepted_declarations)}"
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                paper.series = paper_series
                paper.save()

                # Associate authors
                author_ids = [author_data["id"] for author_data in authors_data]
                authors = Author.objects.filter(id__in=author_ids)
                author_map = {author.id: author for author in authors}

                for author_data in authors_data:
                    author_id = author_data.get("id")
                    institution_id = author_data.get("institution_id")
                    if author_id not in author_map:
                        continue

                    author_position = author_data.get("author_position", "middle")
                    if author_position not in ["first", "middle", "last"]:
                        author_position = "middle"

                    authorship = Authorship.objects.create(
                        paper=paper,
                        author=author_map[author_id],
                        department=author_data.get("department"),
                        email=author_data.get("email"),
                        source="RESEARCHHUB",
                        author_position=author_position,
                        raw_author_name=f"{author_map[author_id].first_name} {author_map[author_id].last_name}",
                        is_corresponding=author_data.get("is_corresponding", False),
                    )

                    if institution_id:
                        authorship.institutions.add(institution_id)

                # Associate hubs
                if hub_ids:
                    paper.hubs.add(*hub_ids)
                    paper.unified_document.hubs.add(*hub_ids)

                # Create paper version
                paper_version_number = 1
                base_doi = None
                original_paper_id = paper.id
                if previous_paper:
                    try:
                        paper_version = previous_paper.version
                        original_paper_id = paper_version.paper_id
                        paper_version_number = paper_version.version + 1
                        if previous_paper.version.base_doi:
                            base_doi = previous_paper.version.base_doi
                    except PaperVersion.DoesNotExist:
                        # If the previous paper version does not exist, create the initial version
                        # and set the current version to 2.
                        original_paper_id = (
                            previous_paper.id
                        )  # The original paper was created outside of ResearchHub
                        PaperVersion.objects.create(
                            paper=previous_paper,
                            version=1,
                            original_paper_id=original_paper_id,
                        )
                        paper_version_number = 2

                doi = DOI(base_doi=base_doi, version=paper_version_number)

                crossref_response = doi.register_doi_for_paper(
                    authors=authors,
                    title=title,
                    rh_paper=paper,
                )

                if crossref_response.status_code != 200:
                    return Response("Crossref API Failure", status=400)

                paper.doi = doi.doi
                paper.save()

                PaperVersion.objects.create(
                    paper=paper,
                    version=paper_version_number,
                    message=change_description,
                    base_doi=doi.base_doi,
                    original_paper_id=original_paper_id,
                )

            # Return serialized paper
            context = self._get_paper_context(request)
            serializer = self.dynamic_serializer_class(
                paper,
                context=context,
                _include_fields=[
                    "id",
                    "title",
                    "abstract",
                    "authors",
                    "hubs",
                    "version",
                    "version_list",
                ],
            )

            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            log_error(e)
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

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
                    "first_name",
                    "last_name",
                    "is_verified",
                ]
            },
            "usr_dus_get_author_profile": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                    "is_verified",
                ]
            },
            "doc_duds_get_concepts": {
                "_include_fields": ["openalex_id", "display_name", "description"]
            },
            "pap_dps_get_hubs": {
                "_exclude_fields": [
                    "editor_permission_groups",
                    "subscribers",
                    "subscriber_count",
                    "paper_count",
                    "discussion_count",
                ]
            },
            "pap_dbs_get_bounties": {
                "_include_fields": [
                    "amount",
                    "created_by",
                    "expiration_date",
                    "id",
                    "status",
                ]
            },
            "pap_dps_get_purchases": {"_include_fields": ["amount", "user"]},
            "rep_dbs_get_created_by": {"_include_fields": ["author_profile", "id"]},
            "pch_dps_get_user": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
        }
        return context

    def _serialize_paper(self, paper, request):
        """
        Common serialization method for papers.
        Used by both retrieve and retrieve_by_doi endpoints.
        """
        context = self._get_paper_context(request)
        serializer = self.dynamic_serializer_class(
            paper,
            context=context,
            _include_fields=[
                "abstract",
                "abstract_src_markdown",
                "authors",
                "boost_amount",
                "created_date",
                "discussion_count",
                "doi",
                "external_source",
                "file",
                "first_preview",
                "id",
                "is_open_access",
                "oa_status",
                "paper_publish_date",
                "paper_title",
                "pdf_file_extract",
                "pdf_license",
                "pdf_url",
                "pdf_copyright_allows_display",
                "peer_reviews",
                "purchases",
                "raw_authors",
                "score",
                "slug",
                "title",
                "work_type",
                "unified_document",
                "uploaded_by",
                "uploaded_date",
                "url",
                "version",
                "version_list",
            ],
        )
        serializer_data = serializer.data
        vote = self.dynamic_serializer_class(context=context).get_user_vote(paper)
        serializer_data["user_vote"] = vote
        return serializer_data

    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve a paper by ID.
        """
        paper = super().get_object()
        serializer_data = self._serialize_paper(paper, request)
        return Response(serializer_data)

    def list(self, request, *args, **kwargs):
        # Temporarily disabling endpoint
        return Response(status=200)

    @sift_track(SIFT_PAPER, is_update=True)
    def update(self, request, *args, **kwargs):
        instance = self.get_object()

        # TODO: This needs improvement so we guarantee that we are tracking
        # file created location when a file is actually being added and not
        # just any updates to the paper
        created_location = None
        if request.query_params.get("created_location") == "progress":
            created_location = Paper.CREATED_LOCATION_PROGRESS
            request.data["file_created_location"] = created_location

        # need to encode before getting passed to serializer
        response = super().update(request, *args, **kwargs)

        if (created_location is not None) and not request.user.is_anonymous:
            instance = self.get_object()
            self._send_created_location_ga_event(instance, request.user)

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

        return Response("Paper was deleted.", status=200)

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[],
    )
    def pdf_coverage(self, request, pk=None):
        date = request.GET.get("date", None)
        paper_query = Paper.objects.all()
        if date:
            paper_query = paper_query.filter(created_date__gte=date)

        paper_count = paper_query.count()
        papers_with_pdfs = paper_query.filter(Q(file="") | Q(file__isnull=True)).count()

        open_access_count = paper_query.filter(is_open_access=True).count()
        open_access_papers_with_pdf = paper_query.filter(
            Q(file="") | Q(file__isnull=True), is_open_access=True
        ).count()

        return Response(
            {
                "paper_count": paper_count,
                "internal_pdf_count": papers_with_pdfs,
                "internal_coverage_percentage": "{}%".format(
                    round(papers_with_pdfs / paper_count, 2) * 100
                ),
                "open_access_count": open_access_count,
                "open_access_pdf_count": open_access_papers_with_pdf,
                "open_access_pdf_percentage": "{}%".format(
                    round(open_access_papers_with_pdf / open_access_count, 2) * 100
                ),
            },
            status=200,
        )

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
        serializer = GrmVoteSerializer(vote)
        return Response(serializer.data, status=200)

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

    @action(
        detail=True,
        methods=["get"],
    )
    def eligible_reward_summary(self, request, pk=None):
        """
        Provides information about rewards for which this paper is eligible for
        """
        paper_id = pk
        if not paper_id:
            return Response("paper_id is required", status=400)

        paper = Paper.objects.get(id=paper_id)
        if not paper:
            return Response("Paper not found", status=404)

        try:
            paper_rewards = paper.paper_rewards
        except Exception:
            return Response("Failed to get paper reward", status=500)

        summary = {
            "base_rewards": paper_rewards,
            "open_access_multiplier": OPEN_ACCESS_MULTIPLIER,
            "open_data_multiplier": OPEN_DATA_MULTIPLIER,
            "preregistration_multiplier": PREREGISTERED_MULTIPLIER,
        }
        return Response(summary, status=200)

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

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def doi_search_via_openalex(self, request):
        doi_string = request.query_params.get("doi", None)
        if doi_string is None:
            return Response(status=400)
        try:
            open_alex = OpenAlex()
            open_alex_json = open_alex.get_data_from_doi(doi_string)
        except Exception:
            return Response(status=404)

        return Response(open_alex_json, status=200)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def fetch_publications_by_doi(self, request):
        doi_string = request.query_params.get("doi", "")
        rh_author = request.user.author_profile

        # Client has the ability (optional) to specify explicilty which OpenAlex ID it wants works for
        openalex_author_id = request.query_params.get("author_id", None)

        if doi_string is None:
            return Response(status=400)

        try:
            # Sometimes user may pass in a doi as doi.org url.
            doi_string = doi_string.replace("https://doi.org/", "").strip()

            try:
                # Fetch data from OpenAlex
                open_alex_api = OpenAlex()
                work = open_alex_api.get_data_from_doi(doi_string)
            except DOINotFoundError:
                return Response(status=404)

            # Next we want to try and guess the author in the list of authors associated with the work.
            # The guess doesn't have to be precise since the user will have the ability to select the correct author.
            # In case we can't guess the author, we will return an error.
            if not openalex_author_id:
                for authorship in work.get("authorships", []):
                    found_openalex_author = None
                    openalex_author = authorship.get("author", {})
                    openalex_author_name = (
                        openalex_author.get("display_name", "").lower().split(" ")
                    )

                    rh_author_first_name = (rh_author.first_name or "").lower()
                    rh_author_last_name = (rh_author.last_name or "").lower()

                    if (
                        rh_author_first_name == openalex_author_name[0]
                        and rh_author_last_name == openalex_author_name[-1]
                    ):
                        found_openalex_author = openalex_author
                    elif (
                        found_openalex_author is None
                        and rh_author_last_name == openalex_author_name[0]
                    ):
                        found_openalex_author = openalex_author
                    elif (
                        found_openalex_author is None
                        and rh_author_first_name == openalex_author_name[-1]
                    ):
                        found_openalex_author = openalex_author

                    if found_openalex_author:
                        openalex_author_id = found_openalex_author.get("id", "")

            # Fetch author works
            author_works = []
            if openalex_author_id:
                openalex_author_id = openalex_author_id.split("/")[-1]
                author_works, _ = open_alex_api.get_works(
                    openalex_author_id=openalex_author_id, batch_size=200
                )
            unclaimed_works = self._filter_unclaimed_works(rh_author, author_works)

            response = {
                "works": unclaimed_works,
                "selected_author_id": openalex_author_id,
                "available_authors": [
                    authorship.get("author")
                    for authorship in work.get("authorships", [])
                ],
            }

            return Response(response, status=200)
        except Exception as error:
            log_error(error)
            return Response(status=500)

    def _filter_unclaimed_works(self, author: Author, openalex_works: list) -> list:
        """
        Returns a list of works that the author has not claimed yet.
        """
        authorships = Authorship.objects.filter(author=author)
        claimed_works = Paper.objects.filter(
            id__in=authorships.values_list("paper_id", flat=True)
        ).values_list("openalex_id", flat=True)
        unclaimed_works = list(
            filter(lambda work: work["id"] not in claimed_works, openalex_works)
        )
        return unclaimed_works

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

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[AllowAny],
    )
    def retrieve_by_doi(self, request):
        """
        Get a paper by DOI or create it if it doesn't exist by importing from OpenAlex.
        Query params:
        - doi: string (required) - The DOI to look up
        """
        doi = request.query_params.get("doi")
        if not doi:
            return Response(
                {"error": "DOI is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate DOI format first
        if not DOI.is_doi(doi):
            return Response(
                {"error": "Invalid DOI format"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Get bare DOI for database lookup
            bare_doi = DOI.get_bare_doi(doi)
            if not bare_doi:
                return Response(
                    {"error": "Invalid DOI format"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Look for existing paper with this DOI
            paper = Paper.objects.filter(Q(doi=bare_doi)).first()
            if paper:
                serializer_data = self._serialize_paper(paper, request)
                return Response(serializer_data)

            # Paper doesn't exist, try to import it from OpenAlex
            return self._create_by_doi(request, doi=bare_doi)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _create_by_doi(self, request, doi):
        """
        Create a paper by fetching data from OpenAlex using a DOI.
        Args:
            doi: Bare DOI (without https://doi.org/ prefix)
        """
        try:
            # Fetch work from OpenAlex
            openalex = OpenAlex()
            work = openalex.get_work_by_doi(doi)
            if not work:
                return Response(
                    {"error": "Work not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Process the work
            from paper.openalex_util import process_openalex_works

            process_openalex_works([work])

            # Get the created paper and serialize it
            paper = Paper.objects.get(doi=doi)
            serializer_data = self._serialize_paper(paper, request)
            return Response(serializer_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            log_error(e)
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class FigureViewSet(viewsets.ModelViewSet):
    queryset = Figure.objects.all()
    serializer_class = FigureSerializer
    throttle_classes = THROTTLE_CLASSES

    permission_classes = [IsObjectOwnerOrModerator]

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

        paper = self.get_object()
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
    permission_classes = [IsAuthenticated | HasAPIKey, PostOnly]

    @track_event
    def create(self, *args, **kwargs):
        data = self.request.data
        url = data.get("url", "")

        # Appends http if protocol does not exist
        parsed_url = urlparse(url)
        if not parsed_url.scheme:
            url = f"http://{parsed_url.geturl()}"
            data["url"] = url

        duplicate_papers = Paper.objects.filter(
            Q(url_svf=SearchQuery(url)) | Q(pdf_url_svf=SearchQuery(url))
        )

        if duplicate_papers:
            serializer = DynamicPaperSerializer(
                duplicate_papers,
                _include_fields=[
                    "doi",
                    "id",
                    "title",
                    "url",
                    "uploaded_by",
                    "created_date",
                ],
                context={
                    "pap_dps_get_uploaded_by": {
                        "_include_fields": ("id", "first_name", "last_name")
                    }
                },
                many=True,
            )
            duplicate_data = {"data": serializer.data}
            return Response(duplicate_data, status=status.HTTP_403_FORBIDDEN)

        data["uploaded_by"] = self.request.user.id
        response = super().create(*args, **kwargs)
        if response.status_code == 201:
            data = response.data
            celery_process_paper(data["id"])
        return response

    @track_event
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
        duplicate_papers = Paper.objects.filter(doi_svf=SearchQuery(doi))
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
            celery_process_paper(data["id"])
        return response
