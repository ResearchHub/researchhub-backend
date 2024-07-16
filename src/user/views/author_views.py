import hmac
from datetime import datetime, timedelta
from hashlib import sha1

from allauth.account.models import EmailAddress
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models import Exists, F, OuterRef, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.timezone import now
from django.views.decorators.cache import cache_page
from django_filters.rest_framework import DjangoFilterBackend
from requests.exceptions import HTTPError
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param
from simple_history.utils import bulk_update_with_history

import utils.sentry as sentry
from discussion.models import Comment, Reply, Thread
from discussion.serializers import DynamicThreadSerializer
from hypothesis.related_models.hypothesis import Hypothesis
from paper.models import Paper
from paper.openalex_util import merge_openalex_author_with_researchhub_author
from paper.serializers import DynamicPaperSerializer
from paper.tasks import pull_openalex_author_works, pull_openalex_author_works_batch
from paper.utils import PAPER_SCORE_Q_ANNOTATION, get_cache_key
from paper.views import PaperViewSet
from reputation.models import Bounty, BountySolution, Contribution, Distribution
from reputation.serializers import (
    DynamicBountySerializer,
    DynamicBountySolutionSerializer,
    DynamicContributionSerializer,
)
from reputation.views import BountyViewSet
from researchhub.settings import (
    EMAIL_WHITELIST,
    SIFT_MODERATION_WHITELIST,
    SIFT_WEBHOOK_SECRET_KEY,
    TESTING,
)
from researchhub_comment.models import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from researchhub_document.serializers import DynamicPostSerializer
from researchhub_document.serializers.researchhub_unified_document_serializer import (
    DynamicUnifiedDocumentSerializer,
)
from researchhub_document.views.researchhub_unified_document_views import (
    ResearchhubUnifiedDocumentViewSet,
)
from review.models.review_model import Review
from user.filters import AuthorFilter, UserFilter
from user.models import Author, Follow, Major, University, User, UserApiToken
from user.permissions import (
    Censor,
    DeleteAuthorPermission,
    DeleteUserPermission,
    HasVerificationPermission,
    IsVerifiedUser,
    RequestorIsOwnUser,
    UpdateAuthor,
)
from user.serializers import (
    AuthorEditableSerializer,
    AuthorSerializer,
    DynamicAuthorProfileSerializer,
    DynamicUserSerializer,
    MajorSerializer,
    UniversitySerializer,
    UserActions,
    UserEditableSerializer,
    UserSerializer,
)
from user.tasks import handle_spam_user_task, reinstate_user_task
from user.utils import (
    AuthorClaimException,
    calculate_show_referral,
    claim_openalex_author_profile,
    reset_latest_acitvity_cache,
)
from utils.http import POST, RequestMethods
from utils.openalex import OpenAlex
from utils.permissions import CreateOrUpdateIfAllowed
from utils.sentry import log_error, log_info
from utils.throttles import THROTTLE_CLASSES


class AuthorViewSet(viewsets.ModelViewSet):
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    filter_class = AuthorFilter
    search_fields = ("first_name", "last_name")
    permission_classes = [
        (IsAuthenticatedOrReadOnly & UpdateAuthor & CreateOrUpdateIfAllowed)
        | DeleteAuthorPermission
    ]
    throttle_classes = THROTTLE_CLASSES

    def create(self, request, *args, **kwargs):
        """Override to use an editable serializer."""
        serializer = AuthorEditableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    def update(self, request, *args, **kwargs):
        """Override to use an editable serializer."""
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = AuthorEditableSerializer(
            instance, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        if getattr(instance, "_prefetched_objects_cache", None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)

    @action(detail=True, methods=["post"], permission_classes=[IsVerifiedUser])
    def claim_profile_and_add_publications(self, request, pk=None):
        author = request.user.author_profile
        openalex_ids = request.data.get("openalex_ids", [])
        openalex_author_id = request.data.get("openalex_author_id", None)

        # Ensure the openalex author id is a full url since it is the format stored in our system
        if "openalex.org" not in openalex_author_id:
            raise Exception("Invalid OpenAlex author ID")

        # Attempt to associate the openalex author id with the RH author
        try:
            claim_openalex_author_profile(author.id, openalex_author_id)
        except AuthorClaimException as e:
            return Response({"reason": e.reason}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if len(openalex_ids) > 0:
            if TESTING:
                pull_openalex_author_works_batch(openalex_ids, request.user.id)
            else:
                pull_openalex_author_works_batch.apply_async(
                    (
                        openalex_ids,
                        request.user.id,
                    ),
                    priority=1,
                )

        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def add_publications(self, request, pk=None):
        openalex_ids = request.data.get("openalex_ids", [])

        if len(openalex_ids) > 0:
            if TESTING:
                pull_openalex_author_works_batch(openalex_ids, request.user.id)
            else:
                pull_openalex_author_works_batch.apply_async(
                    (
                        openalex_ids,
                        request.user.id,
                    ),
                    priority=1,
                )

        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def profile(self, request, pk=None):
        author = self.get_object()
        serializer = DynamicAuthorProfileSerializer(
            author,
            context={
                "author_institution::get_institution": {
                    "_include_fields": [
                        "id",
                        "display_name",
                        "region",
                        "city",
                        "latitude",
                        "longitude",
                        "image_url",
                        "image_thumbnail_url",
                    ]
                },
                "author_profile::get_institutions": {
                    "_include_fields": [
                        "id",
                        "years",
                        "is_primary",
                        "institution",
                    ]
                },
                "author_profile::get_reputation": {
                    "_include_fields": [
                        "hub_id",
                        "hub_name",
                        "hub_slug",
                        "score",
                        "bins",
                    ]
                },
                "author_profile::get_reputation_list": {
                    "_include_fields": [
                        "hub_id",
                        "hub_name",
                        "hub_slug",
                        "score",
                        "bins",
                    ]
                },
                "author_profile::activity_by_year": {
                    "_include_fields": [
                        "year",
                        "works_count",
                        "citation_count",
                    ]
                },
                "author_profile::get_coauthors": {
                    "_include_fields": [
                        "id",
                        "first_name",
                        "last_name",
                        "count",
                        "is_verified",
                        "profile_image",
                        "headline",
                        "description",
                    ]
                },
            },
            _include_fields=(
                "id",
                "openalex_ids",
                "first_name",
                "last_name",
                "description",
                "headline",
                "profile_image",
                "orcid_id",
                "h_index",
                "i10_index",
                "google_scholar",
                "linkedin",
                "twitter",
                "institutions",
                "created_date",
                "country_code",
                "coauthors",
                "reputation",
                "reputation_list",
                "summary_stats",
                "activity_by_year",
                "open_access_pct",
                "achievements",
            ),
        )
        return Response(serializer.data, status=200)

    @action(
        detail=True,
        methods=["get"],
    )
    def get_authored_papers(self, request, pk=None):
        author = self.get_object()
        prefetch_lookups = PaperViewSet.prefetch_lookups(self)
        authored_papers = (
            author.authored_papers.filter(is_removed=False)
            .prefetch_related(
                *prefetch_lookups,
            )
            .annotate(paper_score=PAPER_SCORE_Q_ANNOTATION)
            .order_by("-paper_score")
        )
        context = self._get_authored_papers_context()
        page = self.paginate_queryset(authored_papers)
        serializer = DynamicPaperSerializer(
            page,
            _include_fields=[
                "id",
                "abstract",
                "authors",
                "boost_amount",
                "file",
                "first_preview",
                "hubs",
                "paper_title",
                "score",
                "title",
                "uploaded_by",
                "uploaded_date",
                "url",
                "paper_publish_date",
                "slug",
                "created_date",
            ],
            many=True,
            context=context,
        )
        response = self.get_paginated_response(serializer.data)
        return response

    def _get_authored_papers_context(self):
        context = {
            "pap_dps_get_authors": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                ]
            },
            "pap_dps_get_uploaded_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "pap_dps_get_first_preview": {
                "_include_fields": [
                    "file",
                ]
            },
            "pap_dps_get_hubs": {
                "_include_fields": (
                    "id",
                    "slug",
                    "name",
                )
            },
            "usr_dus_get_author_profile": {
                "_include_fields": ["id", "first_name", "last_name", "profile_image"]
            },
            "doc_duds_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "slug",
                    "hub_image",
                ]
            },
        }
        return context

    def _get_contribution_context(self, filter_by_user_id):
        context = {
            "request": self.request,
            "_config": {
                "filter_by_user_id": filter_by_user_id,
            },
            "doc_dps_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "doc_duds_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "doc_dps_get_hubs": {
                "_include_fields": [
                    "name",
                    "slug",
                ]
            },
            "pap_dps_get_uploaded_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "dis_dts_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "dis_dts_get_review": {
                "_include_fields": [
                    "id",
                    "score",
                ]
            },
            "dis_dcs_get_created_by": {
                "_include_fields": [
                    "author_profile",
                    "id",
                ]
            },
            "dis_drs_get_created_by": {
                "_include_fields": [
                    "author_profile",
                    "id",
                ]
            },
            "pap_dps_get_user_vote": {
                "_include_fields": [
                    "id",
                    "created_by",
                    "created_date",
                    "vote_type",
                ]
            },
            "pap_dps_get_hubs": {
                "_include_fields": [
                    "name",
                    "slug",
                ]
            },
            "pap_dpvs_paper": {"_exclude_fields": "__all__"},
            "doc_dps_get_user_vote": {
                "_include_fields": [
                    "id",
                    "content_type",
                    "created_by",
                    "created_date",
                    "vote_type",
                    "item",
                ]
            },
            "dis_drs_get_user_vote": {
                "_include_fields": [
                    "id",
                    "content_type",
                    "created_by",
                    "created_date",
                    "vote_type",
                    "item",
                ]
            },
            "dis_dcs_get_user_vote": {
                "_include_fields": [
                    "id",
                    "content_type",
                    "created_by",
                    "created_date",
                    "vote_type",
                    "item",
                ]
            },
            "dis_dts_get_user_vote": {
                "_include_fields": [
                    "id",
                    "content_type",
                    "created_by",
                    "created_date",
                    "vote_type",
                    "item",
                ]
            },
            "dis_dts_get_comments": {
                "_include_fields": [
                    "created_by",
                    "created_date",
                    "updated_date",
                    "created_location",
                    "external_metadata",
                    "id",
                    "is_created_by_editor",
                    "is_public",
                    "is_removed",
                    "paper_id",
                    "parent",
                    "plain_text",
                    "promoted",
                    "replies",
                    "reply_count",
                    "score",
                    "source",
                    "text",
                    "thread_id",
                    "user_flag",
                    "user_vote",
                    "was_edited",
                ]
            },
            "dis_dcs_get_replies": {
                "_include_fields": [
                    "created_by",
                    "created_location",
                    "id",
                    "is_created_by_editor",
                    "is_public",
                    "is_removed",
                    "paper_id",
                    "parent",
                    "plain_text",
                    "promoted",
                    "score",
                    "text",
                    "thread_id",
                    "user_flag",
                    "user_vote",
                    "created_date",
                    "updated_date",
                ]
            },
            "doc_duds_get_documents": {
                "_include_fields": [
                    "promoted",
                    "abstract",
                    "aggregate_citation_consensus",
                    "created_by",
                    "created_date",
                    "hot_score",
                    "hubs",
                    "id",
                    "discussion_count",
                    "paper_title",
                    "preview_img",
                    "renderable_text",
                    "score",
                    "slug",
                    "title",
                    "uploaded_by",
                    "uploaded_date",
                    "user_vote",
                ]
            },
            "doc_duds_get_bounties": {"_include_fields": ["id"]},
            "doc_duds_get_document_filter": {
                "_include_fields": [
                    "answered",
                    "bounty_open",
                    "bounty_total_amount",
                ]
            },
            "rep_dcs_get_author": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                ]
            },
            "rep_dcs_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "documents",
                    "hubs",
                    "document_filter",
                ]
            },
            "rep_dcs_get_source": {
                "_include_fields": [
                    "amount",
                    "citation",
                    "comment_count",
                    "comment_content_json",
                    # 02-18-24 Kobe: Temporarily commenting this out as it leads to a fatal error.
                    # I'm not sure this key is necessary for the client. Only time will tell
                    # "children",
                    "content_type",
                    "created_by",
                    "created_date",
                    "created_location",
                    "discussion_type",
                    "document_meta",
                    "external_metadata",
                    "hypothesis",
                    "id",
                    "is_public",
                    "is_removed",
                    "paper_slug",
                    "paper_title",
                    "paper",
                    "plain_text",
                    "post_slug",
                    "post",
                    "promoted",
                    "replies",
                    "review",
                    "score",
                    "slug",
                    "source",
                    "text",
                    "title",
                    "user_flag",
                    "user_vote",
                    "vote",
                    "bet_amount",
                ]
            },
            "rep_dbs_get_item": {
                "_include_fields": [
                    "created_by",
                    "created_date",
                    "updated_date",
                    "created_location",
                    "external_metadata",
                    "id",
                    "is_created_by_editor",
                    "is_public",
                    "is_removed",
                    "paper_id",
                    "parent",
                    "plain_text",
                    "promoted",
                    "replies",
                    "reply_count",
                    "score",
                    "source",
                    "text",
                    "thread_id",
                    "paper",
                    "post",
                    "awarded_bounty_amount",
                    "unified_document",
                    "user_flag",
                    "user_vote",
                    "was_edited",
                ]
            },
            "rep_dbss_get_item": {
                "_include_fields": [
                    "created_by",
                    "created_date",
                    "updated_date",
                    "created_location",
                    "external_metadata",
                    "id",
                    "is_created_by_editor",
                    "is_public",
                    "is_removed",
                    "paper_id",
                    "parent",
                    "plain_text",
                    "promoted",
                    "replies",
                    "reply_count",
                    "score",
                    "source",
                    "text",
                    "awarded_bounty_amount",
                    "thread_id",
                    "user_flag",
                    "user_vote",
                    "was_edited",
                ]
            },
            "rep_dbs_get_created_by": {"_include_fields": ["author_profile", "id"]},
            "dis_dts_get_bounties": {
                "_include_fields": [
                    "amount",
                    "created_by",
                ]
            },
            "dis_dts_get_paper": {
                "_include_fields": [
                    "id",
                    "slug",
                ]
            },
            "dis_dts_get_post": {
                "_include_fields": [
                    "id",
                    "slug",
                ]
            },
            "doc_duds_get_hubs": {
                "_include_fields": [
                    "name",
                    "slug",
                ]
            },
            "hyp_dhs_get_hubs": {
                "_include_fields": [
                    "name",
                    "slug",
                ]
            },
            "hyp_dhs_get_created_by": {
                "_include_fields": [
                    "author_profile",
                    "id",
                ]
            },
            "rhc_dcs_get_created_by": {
                "_include_fields": [
                    "first_name",
                    "last_name",
                    "author_profile",
                ]
            },
            "rhc_dcs_get_children": {
                "_exclude_fields": [
                    "thread",
                    "comment_content_src",
                    "promoted",
                    "user_endorsement",
                    "user_flag",
                    "purchases",
                ]
            },
            "rhc_dcs_get_purchases": {
                "_include_fields": [
                    "amount",
                    "user",
                ]
            },
            "rev_drs_get_created_by": {
                "_include_fields": [
                    "author_profile",
                    "id",
                ]
            },
            "pch_dps_get_user": {
                "_include_fields": [
                    "author_profile",
                    "id",
                ]
            },
        }
        return context

    @action(
        detail=True,
        methods=["get"],
    )
    def overview(self, request, pk=None):
        author = self.get_object()

        # We want to only return a few documents for the overview section
        NUM_DOCUMENTS_TO_FETCH = 4

        # Fetch the authored papers and order by citations
        authored_doc_ids = list(
            author.authored_papers.filter(is_removed=False)
            .order_by("-citations")
            .values_list("unified_document_id", flat=True)
        )[:NUM_DOCUMENTS_TO_FETCH]

        documents = ResearchhubUnifiedDocument.objects.filter(id__in=authored_doc_ids)

        # Maintain the ordering authored papers
        documents_ordered = sorted(
            documents, key=lambda x: authored_doc_ids.index(x.id)
        )

        context = ResearchhubUnifiedDocumentViewSet._get_serializer_context(self)
        page = self.paginate_queryset(documents_ordered)

        serializer = DynamicUnifiedDocumentSerializer(
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

    @action(
        detail=True,
        methods=["get"],
    )
    def contributions(self, request, pk=None):
        author = self.get_object()

        query_params = request.query_params
        ordering = query_params.get("ordering", "-created_date")
        asset_type = query_params.get("type", "overview")
        contributions = self._get_author_contribution_queryset(
            author.id, ordering, asset_type
        )

        page = self.paginate_queryset(contributions)
        context = self._get_contribution_context(author.user_id)
        serializer = DynamicContributionSerializer(
            page,
            _include_fields=[
                "contribution_type",
                "created_date",
                "id",
                "source",
                "created_by",
                "unified_document",
                "author",
            ],
            context=context,
            many=True,
        )
        data = serializer.data
        response = self.get_paginated_response(data)
        if asset_type == "bounty_offered":
            total_bounty_amount = contributions.aggregate(
                total_amount=Sum("bounty__amount")
            )
            response.data["total_bounty_amount"] = total_bounty_amount.get(
                "total_amount", 0
            )

        return response

    def _get_author_comments(self, author_id):
        author = self.get_object()
        user = author.user

        if user:
            user_threads = RhCommentModel.objects.filter(Q(created_by=user))
            return user_threads
        return []

    def _get_author_contribution_queryset(self, author_id, ordering, asset_type):
        author_comments = self._get_author_comments(author_id)
        rh_comment_content_type = ContentType.objects.get_for_model(RhCommentModel)
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        paper_content_type = ContentType.objects.get_for_model(Paper)
        hypothesis_content_type = ContentType.objects.get_for_model(Hypothesis)
        review_content_type = ContentType.objects.get_for_model(Review)
        bounty_content_type = ContentType.objects.get_for_model(Bounty)
        bounty_solution_content_type = ContentType.objects.get_for_model(BountySolution)

        types = asset_type.split(",")

        query = Q()
        for asset_type in types:
            if asset_type == "overview":
                query |= Q(
                    Q(
                        unified_document__is_removed=False,
                        content_type=rh_comment_content_type,
                        # we filter by object_id instead of author_profile because
                        # sometimes there's contributions without a matching comment.
                        # this method ensures the comments exists.
                        object_id__in=author_comments,
                        contribution_type__in=[
                            Contribution.COMMENTER,
                        ],
                    )
                    | Q(
                        unified_document__is_removed=False,
                        user__author_profile=author_id,
                        content_type_id__in=[
                            hypothesis_content_type,
                            paper_content_type,
                            post_content_type,
                            review_content_type,
                        ],
                        contribution_type__in=[
                            Contribution.SUBMITTER,
                            Contribution.SUPPORTER,
                        ],
                    )
                )
            elif asset_type == "discussion":
                query |= Q(
                    unified_document__is_removed=False,
                    user__author_profile=author_id,
                    content_type_id=post_content_type,
                    contribution_type__in=[Contribution.SUBMITTER],
                )
            elif asset_type == "hypothesis":
                query |= Q(
                    unified_document__is_removed=False,
                    user__author_profile=author_id,
                    content_type_id=hypothesis_content_type,
                    contribution_type__in=[Contribution.SUBMITTER],
                )
            elif asset_type == "comment":
                query |= Q(
                    unified_document__is_removed=False,
                    content_type=rh_comment_content_type,
                    # we filter by object_id instead of author_profile because
                    # sometimes there's contributions without a matching comment.
                    # this method ensures the comments exists.
                    object_id__in=author_comments,
                    contribution_type__in=[Contribution.COMMENTER],
                )
            elif asset_type == "paper":
                query |= Q(
                    unified_document__is_removed=False,
                    user__author_profile=author_id,
                    content_type_id=paper_content_type,
                    contribution_type__in=[Contribution.SUBMITTER],
                )
            elif asset_type == "bounty_offered":
                query |= Q(
                    unified_document__is_removed=False,
                    user__author_profile=author_id,
                    content_type_id=bounty_content_type,
                    contribution_type__in=[Contribution.BOUNTY_CREATED],
                )
            elif asset_type == "bounty_earned":
                query |= Q(
                    unified_document__is_removed=False,
                    user__author_profile=author_id,
                    content_type_id=bounty_solution_content_type,
                    contribution_type__in=[Contribution.BOUNTY_SOLUTION],
                )
            else:
                raise Exception("Unrecognized asset type: {}".format(asset_type))

        qs = (
            Contribution.objects.filter(query)
            .select_related(
                "content_type",
                "user",
                "user__author_profile",
                "unified_document",
            )
            .order_by(ordering)
        )

        return qs

    @action(
        detail=True,
        methods=["get"],
    )
    def get_user_discussions(self, request, pk=None):
        author = self.get_object()
        user = author.user

        if user:
            user_discussions = user.thread_set.filter(is_removed=False).order_by("-id")
        else:
            user_discussions = self.queryset.none()

        page = self.paginate_queryset(user_discussions)
        context = self._get_user_discussion_context()
        serializer = DynamicThreadSerializer(
            page,
            _include_fields=[
                "id",
                "comment_count",
                "created_by",
                "created_date",
                "paper",
                "post",
                "score",
                "text",
            ],
            many=True,
            context=context,
        )
        return self.get_paginated_response(serializer.data)

    def _get_user_discussion_context(self):
        context = {
            "dis_dts_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "dis_dts_get_paper": {
                "_include_fields": [
                    "id",
                    "slug",
                ]
            },
            "dis_dts_get_post": {
                "_include_fields": [
                    "id",
                    "slug",
                ]
            },
            "usr_dus_get_author_profile": {
                "_include_fields": ["id", "first_name", "last_name", "profile_image"]
            },
        }
        return context

    @action(
        detail=True,
        methods=["get"],
    )
    def get_user_contributions(self, request, pk=None):
        author = self.get_object()
        user = author.user

        if user:
            prefetch_lookups = PaperViewSet.prefetch_lookups(self)
            user_paper_uploads = user.papers.filter(is_removed=False).prefetch_related(
                *prefetch_lookups
            )
        else:
            user_paper_uploads = self.queryset.none()

        context = self._get_user_contributions_context()
        page = self.paginate_queryset(user_paper_uploads)
        serializer = DynamicPaperSerializer(
            page,
            _include_fields=[
                "id",
                "abstract",
                "boost_amount",
                "file",
                "hubs",
                "paper_title",
                "score",
                "title",
                "slug",
                "uploaded_by",
                "uploaded_date",
            ],
            many=True,
            context=context,
        )
        response = self.get_paginated_response(serializer.data)

        return response

    def _get_user_contributions_context(self):
        context = {
            "pap_dps_get_uploaded_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "usr_dus_get_author_profile": {
                "_include_fields": ["id", "first_name", "last_name", "profile_image"]
            },
            "doc_duds_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "slug",
                    "hub_image",
                ]
            },
        }
        return context

    @action(
        detail=True,
        methods=["get"],
    )
    def get_user_posts(self, request, pk=None):
        author = self.get_object()
        user = author.user

        if user:
            user_posts = user.created_posts.all().prefetch_related(
                "unified_document", "purchases"
            )
        else:
            user_posts = self.queryset.none()

        context = self._get_user_posts_context()
        page = self.paginate_queryset(user_posts)
        serializer = DynamicPostSerializer(
            page,
            _include_fields=[
                "id",
                "created_by",
                "hubs",
                "boost_amount",
                "renderable_text",
                "score",
                "slug",
                "title",
            ],
            many=True,
            context=context,
        )
        response = self.get_paginated_response(serializer.data)
        return response

    def _get_user_posts_context(self):
        context = {
            "doc_dps_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "usr_dus_get_author_profile": {
                "_include_fields": ["id", "first_name", "last_name", "profile_image"]
            },
            "doc_dps_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "slug",
                    "hub_image",
                ]
            },
        }
        return context
