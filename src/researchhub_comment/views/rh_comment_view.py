from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Prefetch
from django.db.models.query import QuerySet
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from analytics.amplitude import track_event
from discussion.permissions import EditorCensorDiscussion
from discussion.views import ReactionViewActionMixin
from reputation.models import Bounty, Contribution
from reputation.tasks import create_contribution, find_qualified_users_and_notify
from reputation.utils import deduct_bounty_fees
from reputation.views.bounty_view import _create_bounty, _create_bounty_checks
from researchhub.pagination import FasterDjangoPaginator
from researchhub.permissions import IsObjectOwner, IsObjectOwnerOrModerator
from researchhub.settings import TESTING
from researchhub_access_group.constants import ADMIN, EDITOR, PRIVATE, PUBLIC, WORKSPACE
from researchhub_access_group.models import Permission
from researchhub_comment.constants.rh_comment_thread_types import (
    AUTHOR_UPDATE,
    COMMUNITY_REVIEW,
    GENERIC_COMMENT,
)
from researchhub_comment.constants.rh_comment_view_constants import (
    HYPOTHESIS,
    PAPER,
    RESEARCHHUB_POST,
)
from researchhub_comment.filters import RHCommentFilter
from researchhub_comment.models import RhCommentModel
from researchhub_comment.permissions import (
    CanSetAsAcceptedAnswer,
    IsThreadCreator,
    ThreadViewingPermissions,
)
from researchhub_comment.serializers import (
    DynamicRhCommentSerializer,
    RhCommentSerializer,
    RhCommentThreadSerializer,
)
from researchhub_comment.tasks import celery_create_mention_notification
from researchhub_document.related_models.constants.document_type import (
    FILTER_BOUNTY_OPEN,
    FILTER_HAS_BOUNTY,
    SORT_BOUNTY_EXPIRATION_DATE,
    SORT_BOUNTY_TOTAL_AMOUNT,
    SORT_DISCUSSED,
)
from review.services.review_service import (
    MAX_REVIEWS_PER_WINDOW,
    REVIEW_WINDOW_DAYS,
    get_review_availability,
)
from utils.throttles import THROTTLE_CLASSES


def remove_bounties(comment):
    for bounty in comment.bounties.iterator():
        cancelled = bounty.close(Bounty.CANCELLED)
        if not cancelled:
            raise Exception("Failed to close bounties on comment")


class CommentPagination(PageNumberPagination):
    django_paginator_class = FasterDjangoPaginator
    page_size_query_param = "page_size"
    # Large max page size needed for inline comments since they are not paginated and need to be load all at once
    max_page_size = 500
    page_size = 500


class RhCommentViewSet(ReactionViewActionMixin, ModelViewSet):
    queryset = RhCommentModel.objects.all()
    serializer_class = RhCommentSerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = RHCommentFilter
    pagination_class = CommentPagination
    permission_classes = [
        IsAuthenticatedOrReadOnly,
        IsObjectOwner,
        ThreadViewingPermissions,
    ]
    throttle_classes = THROTTLE_CLASSES
    _ALLOWED_MODEL_NAMES = (PAPER, RESEARCHHUB_POST, HYPOTHESIS)
    _CONTENT_TYPE_MAPPINGS = {
        PAPER: "paper",
        RESEARCHHUB_POST: "researchhubpost",
        HYPOTHESIS: "hypothesis",
    }
    _ALLOWED_UPDATE_FIELDS = set(
        ["comment_content_type", "comment_content_json", "context_title", "mentions"]
    )

    def dispatch(self, request, *args, **kwargs):
        """Initialize service dependencies for better testability."""
        from paper.services.paper_version_service import PaperService

        self.paper_service = kwargs.pop("paper_service", PaperService())
        return super().dispatch(request, *args, **kwargs)

    def _get_model_name(self):
        kwargs = self.kwargs
        model_name = kwargs.get("model")
        return model_name

    def _get_model_object_id(self):
        kwargs = self.kwargs
        model_object_id = kwargs.get("model_object_id")
        return model_object_id

    def _get_content_type_model(self, model_name):
        key = self._CONTENT_TYPE_MAPPINGS[model_name]
        content_type = ContentType.objects.get(model=key)
        return content_type

    def _get_model_object(self):
        model_name = self._get_model_name()
        model_object_id = self._get_model_object_id()

        assert (
            model_object_id is not None
            and model_name is not None
            and model_name in self._ALLOWED_MODEL_NAMES
        ), f"{model_name} is not an accepted model"

        model = self._get_content_type_model(model_name).model_class()
        model_object = model.objects.get(id=model_object_id)
        return model_object

    def _get_model_object_threads(self):
        model_name = self._get_model_name()
        model_object = self._get_model_object()

        # Special handling for Paper model to get comments from all versions
        if model_name == PAPER:
            from django.contrib.contenttypes.models import ContentType

            # Get content type for Paper model
            paper_content_type = ContentType.objects.get_for_model(model_object)

            # Get all versions of the paper using injected service or create default
            if not hasattr(self, "paper_service"):
                from paper.services.paper_version_service import PaperService

                self.paper_service = PaperService()

            paper_versions = self.paper_service.get_all_paper_versions(model_object.id)

            # Get threads for all paper versions
            from researchhub_comment.models import RhCommentThreadModel

            thread_queryset = RhCommentThreadModel.objects.filter(
                content_type=paper_content_type,
                object_id__in=paper_versions.values_list("id", flat=True),
            )
            return thread_queryset
        else:
            # Normal handling for other models
            thread_queryset = model_object.rh_threads.all()
            return thread_queryset

    def get_queryset(self):
        """
        Taken from DRF source code
        """
        assert self.queryset is not None, (
            "'%s' should either include a `queryset` attribute, "
            "or override the `get_queryset()` method." % self.__class__.__name__
        )

        # Custom logic start
        thread_queryset = self._get_model_object_threads().values_list("id")
        queryset = RhCommentModel.objects.filter(thread__in=thread_queryset)
        # Custom logic end

        if isinstance(queryset, QuerySet):
            # Ensure queryset is re-evaluated on each request.
            queryset = queryset.all()
        return queryset

    def get_serializer(self, *args, **kwargs):
        """
        Taken from DRF source code
        """
        serializer_class = self.get_serializer_class()
        kwargs.setdefault("context", self.get_serializer_context())
        # Custom logic start
        is_dynamic = serializer_class == DynamicRhCommentSerializer
        if is_dynamic and (
            "_include_fields" not in kwargs and "_exclude_fields" not in kwargs
        ):
            kwargs.setdefault("_exclude_fields", "__all__")
        # Custom logic end

        return serializer_class(*args, **kwargs)

    def get_serializer_class(self):
        if self.action in ("create_rh_comment", "partial_update"):
            return super().get_serializer_class()
        return DynamicRhCommentSerializer

    def _get_retrieve_context(self):
        context = self.get_serializer_context()
        context = {
            **context,
            "rhc_dcs_get_thread": {
                "_include_fields": (
                    "anchor",
                    "content_type",
                    "id",
                    "object_id",
                    "privacy_type",
                    "thread_type",
                    "peer_review",
                )
            },
            "rhc_dcs_get_created_by": {
                "_include_fields": (
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                    "is_verified",
                    "editor_of",
                )
            },
            "rhc_dcs_get_children": {
                "_exclude_fields": (
                    "comment_content_src",
                    "promoted",
                    "user_endorsement",
                    "user_flag",
                ),
                "_select_related_fields": (
                    "created_by",
                    "created_by__author_profile",
                    "thread",
                ),
                "_prefetch_related_fields": (
                    "children",
                    "purchases",
                    "bounties",
                    "bounties__parent",
                    "bounties__created_by",
                    "bounties__created_by__author_profile",
                    "bounties__solutions",
                    "bounties__solutions__created_by",
                    "bounties__solutions__created_by__author_profile",
                    "reviews",
                    "thread__permissions",
                    "thread__content_type",
                    Prefetch(
                        "created_by__permissions",
                        queryset=Permission.objects.filter(
                            access_type=EDITOR,
                            content_type__model="hub",
                        ),
                        to_attr="created_by_permissions",
                    ),
                ),
            },
            "rhc_dcs_get_purchases": {"_include_fields": ("amount", "user")},
            "rhc_dcs_get_bounties": {
                "_include_fields": [
                    "bounty_type",
                    "amount",
                    "awarded_bounty_amount",
                    "created_by",
                    "status",
                    "id",
                    "parent",
                    "expiration_date",
                    "solutions",
                ]
            },
            "rep_dbs_get_solutions": {
                "_include_fields": [
                    "id",
                    "status",
                    "awarded_amount",
                    "created_by",
                    "content_type",
                    "object_id",
                ]
            },
            "rep_dbss_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                    "is_verified",
                ]
            },
            "rhc_dcs_get_review": {
                "_include_fields": [
                    "score",
                    "id",
                    "object_id",
                    "is_assessed",
                ]
            },
            "rep_dbs_get_parent": {"_include_fields": ("id",)},
            "rep_dbs_get_created_by": {"_include_fields": ["author_profile", "id"]},
            "usr_dus_get_author_profile": {
                "_include_fields": (
                    "id",
                    "first_name",
                    "last_name",
                    "created_date",
                    "updated_date",
                    "profile_image",
                    "is_verified",
                )
            },
            "usr_dus_get_editor_of": {"_include_fields": ("source",)},
            "rag_dps_get_source": {
                "_include_fields": ("id", "name", "hub_image", "slug")
            },
            "pch_dps_get_user": {
                "_include_fields": ("id", "author_profile", "first_name", "last_name")
            },
        }
        return context

    def _create_rh_comment(self, request, *args, **kwargs):
        data = request.data
        user = request.user
        model = self._get_model_name()

        # Enforce rate limit for community reviews
        if data.get("comment_type") == COMMUNITY_REVIEW:
            availability = get_review_availability(user)
            if not availability.can_review:
                raise PermissionDenied(
                    f"You can only create {MAX_REVIEWS_PER_WINDOW} reviews every {REVIEW_WINDOW_DAYS} days."
                )

        # Enforce author-only for author updates
        if data.get("thread_type") == AUTHOR_UPDATE:
            target = self._get_model_object()
            if not getattr(target, "created_by", None) or target.created_by != user:
                raise PermissionDenied("Only the author can add author updates.")

        with transaction.atomic():
            rh_thread, parent_id = self._retrieve_or_create_thread_from_request(request)
            data.update(
                {
                    "created_by": user.id,
                    "updated_by": user.id,
                    "thread": rh_thread.id,
                    "parent": parent_id,
                }
            )
            rh_comment, _ = RhCommentModel.create_from_data(data)

            unified_document = rh_comment.unified_document
            self.add_upvote(user, rh_comment)
            self._create_mention_notifications_from_request(request, rh_comment.id)
            create_contribution.apply_async(
                (
                    Contribution.COMMENTER,
                    {"app_label": "researchhub_comment", "model": "rhcommentmodel"},
                    request.user.id,
                    unified_document.id,
                    rh_comment.id,
                ),
                priority=1,
                countdown=10,
            )

            context = self._get_retrieve_context()
            serializer_data = DynamicRhCommentSerializer(
                rh_comment,
                context=context,
                _exclude_fields=(
                    "promoted",
                    "user_endorsement",
                    "user_flag",
                    "comment_content_src",
                ),
            ).data
            return Response(serializer_data, status=200)

    @track_event
    @action(
        detail=False, methods=["POST"], permission_classes=[IsAuthenticatedOrReadOnly]
    )
    def create_rh_comment(self, request, *args, **kwargs):
        return self._create_rh_comment(request, *args, **kwargs)

    @track_event
    @action(
        detail=False, methods=["POST"], permission_classes=[IsAuthenticatedOrReadOnly]
    )
    def create_comment_with_bounty(self, request, *args, **kwargs):
        data = request.data
        user = request.user
        amount = data.pop("amount", 0)
        expiration_date = data.pop("expiration_date", None)
        item_content_type = RhCommentModel.__name__.lower()

        # If set, users with expertise matching these hubs will be notified of the bounty
        target_hubs = data.pop("target_hub_ids", [])

        response = _create_bounty_checks(user, amount, item_content_type)
        if not isinstance(response, tuple):
            return response
        else:
            amount, fee_amount, rh_fee, dao_fee, current_bounty_fee = response

        with transaction.atomic():
            comment_response = self._create_rh_comment(request, *args, **kwargs)
            item_object_id = comment_response.data["id"]
            self._create_mention_notifications_from_request(request, item_object_id)
            data["item_content_type"] = item_content_type
            data["item_object_id"] = item_object_id
            if expiration_date:
                data["expiration_date"] = expiration_date

            deduct_bounty_fees(user, fee_amount, rh_fee, dao_fee, current_bounty_fee)
            bounty = _create_bounty(
                user,
                data,
                amount,
                fee_amount,
                current_bounty_fee,
                item_content_type,
                item_object_id,
                rh_fee=rh_fee,
            )
            unified_document = bounty.unified_document
            unified_document.update_filter(SORT_DISCUSSED)
            create_contribution.apply_async(
                (
                    Contribution.BOUNTY_CREATED,
                    {"app_label": "reputation", "model": "bounty"},
                    user.id,
                    unified_document.id,
                    bounty.id,
                ),
                priority=1,
                countdown=10,
            )

            unified_document.update_filters(
                (
                    FILTER_BOUNTY_OPEN,
                    FILTER_HAS_BOUNTY,
                    SORT_BOUNTY_EXPIRATION_DATE,
                    SORT_BOUNTY_TOTAL_AMOUNT,
                )
            )

            rh_comment = self.get_queryset().get(id=item_object_id)
            context = self._get_retrieve_context()
            serializer_data = DynamicRhCommentSerializer(
                rh_comment,
                context=context,
                _exclude_fields=(
                    "promoted",
                    "user_endorsement",
                    "user_flag",
                    "comment_content_src",
                ),
            ).data
            res = Response(serializer_data, status=201)
            res.data["bounty_amount"] = amount  # This is here for Amplitude tracking

            if TESTING:
                find_qualified_users_and_notify(
                    bounty.id, target_hubs, exclude_users=[user.id]
                )
            else:
                find_qualified_users_and_notify.apply_async(
                    (bounty.id, target_hubs, [user.id]), priority=3, countdown=1
                )

            return res

    def create(self, request, *args, **kwargs):
        return Response(
            "Directly creating RhComment with view is prohibited. Use /rh_comment_thread/create_comment",
            status=status.HTTP_400_BAD_REQUEST,
        )

    def destroy(self, request, *args, **kwargs):
        return Response(
            "Deletion is not allowed",
            status=status.HTTP_400_BAD_REQUEST,
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        queryset = queryset.select_related(
            "created_by",
            "created_by__author_profile",
            "thread",
        )
        queryset = queryset.prefetch_related(
            "children",
            "purchases",
            "bounties",
            "bounties__parent",
            "bounties__created_by",
            "bounties__created_by__author_profile",
            "bounties__solutions",
            "bounties__solutions__created_by",
            "bounties__solutions__created_by__author_profile",
            "reviews",
            "thread__permissions",
            "thread__content_type",
            Prefetch(
                "created_by__permissions",
                queryset=Permission.objects.filter(
                    access_type=EDITOR,
                    content_type__model="hub",
                ),
                to_attr="created_by_permissions",
            ),
        )

        page = self.paginate_queryset(queryset)
        context = self._get_retrieve_context()
        if page is not None:
            serializer = self.get_serializer(
                page,
                many=True,
                context=context,
                _exclude_fields=(
                    "promoted",
                    "user_endorsement",
                    "user_flag",
                    "comment_content_src",
                ),
            )
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(
            page,
            many=True,
            context=context,
            _exclude_fields=(
                "promoted",
                "user_endorsement",
                "user_flag",
                "reviews",
                "comment_content_src",
            ),
        )
        return Response(serializer.data)

    def get_object(self):
        """Lookup by pk without applying DRF filter backends."""
        assert self.kwargs.get(
            "pk"
        ), "Expected view to be called with a URL keyword argument named 'pk'"

        queryset = self.get_queryset()

        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}

        obj = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        context = self._get_retrieve_context()
        serializer = self.get_serializer(
            instance,
            context=context,
            _exclude_fields=(
                "promoted",
                "user_endorsement",
                "user_flag",
                "comment_content_src",
            ),
        )
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        if request.method == "PUT":
            return Response(
                "PUT is not allowed",
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = request.data

        with transaction.atomic():
            # This prevents users from changing important fields, e.g., parent or id
            disallowed_keys = set(data.keys()) - self._ALLOWED_UPDATE_FIELDS
            for key in disallowed_keys:
                data.pop(key)
            res = super().update(request, *args, **kwargs)
            comment = self.get_object()
            self._create_mention_notifications_from_request(request, comment.id)
            context = self._get_retrieve_context()
            serializer_data = DynamicRhCommentSerializer(
                comment,
                context=context,
                _exclude_fields=(
                    "promoted",
                    "user_endorsement",
                    "user_flag",
                    "comment_content_src",
                ),
            ).data
            res.data = serializer_data
            return res

    def perform_update(self, serializer):
        instance = serializer.save()
        instance.update_comment_content()

    @action(
        detail=True,
        methods=["put", "patch", "delete"],
        permission_classes=[
            IsAuthenticated,
            (IsObjectOwnerOrModerator | EditorCensorDiscussion),
        ],
    )
    def censor(self, request, *args, **kwargs):
        with transaction.atomic():
            comment = self.get_object()
            remove_bounties(comment)
            censor_response = super().censor(request, *args, **kwargs)
            comment.refresh_related_discussion_count()
            return censor_response

    @action(
        detail=True,
        methods=["GET"],
        permission_classes=[AllowAny],
    )
    def get_comment(self, request, model=None, model_object_id=None, pk=None):
        try:
            comment = self.get_object()
            context = self._get_retrieve_context()
            serializer = self.get_serializer(
                comment,
                context=context,
                _exclude_fields=(
                    "promoted",
                    "user_endorsement",
                    "user_flag",
                    "comment_content_src",
                ),
            )
            return Response(serializer.data, status=200)
        except Exception as error:
            return Response(
                f"Failed - get_comment_threads: {error}",
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(
        detail=True,
        methods=["POST"],
        permission_classes=[IsAuthenticatedOrReadOnly, CanSetAsAcceptedAnswer],
    )
    def mark_as_accepted_answer(self, *args, pk=None, **kwargs):
        with transaction.atomic():
            # This clears prior accepted answers
            comments = self.get_queryset()
            comments.filter(is_accepted_answer=True).update(is_accepted_answer=None)

            comment = self.get_object()
            comment.is_accepted_answer = True
            comment.save()

            return Response({"comment_id": comment.id}, status=200)

    @action(
        detail=True,
        methods=["PATCH"],
        permission_classes=[IsAuthenticated, IsObjectOwner, IsThreadCreator],
    )
    def update_comment_permission(
        self, request, model=None, model_object_id=None, pk=None
    ):
        data = request.data
        user = request.user
        comment = self.get_object()
        thread = comment.thread

        with transaction.atomic():
            model = data.get("content_type")
            object_id = data.get("object_id")

            if (permission_type := data.get("privacy_type", None)) == PRIVATE:
                thread.permissions.all().delete()
                self._create_thread_permission(user, thread, None)
            elif permission_type == WORKSPACE:
                thread.permissions.all().delete()
                organization = getattr(request, "organization", None)
                if organization is None:
                    return Response(status=401)
                self._create_thread_permission(user, thread, organization)
            else:
                thread.permissions.all().delete()
                if model not in self._ALLOWED_MODEL_NAMES:
                    return Response(status=401)

            # When switching between privacy types (public/private/workspace),
            # update the content_type and object_id if they are provided
            # and represent a valid model.
            if model in self._ALLOWED_MODEL_NAMES and object_id:
                try:
                    # Validate that the object_id exists for the given model
                    content_type = self._get_content_type_model(model)
                    model_class = content_type.model_class()
                    if model_class.objects.filter(id=object_id).exists():
                        serializer = RhCommentThreadSerializer(
                            thread,
                            data={
                                "content_type": content_type.id,
                                "object_id": object_id,
                            },
                            partial=True,
                        )
                        serializer.is_valid()
                        serializer.save()
                except Exception:
                    # If there's any issue with the model/object_id, just continue
                    # without updating the content_object reference
                    pass

            return Response(status=200)

    def _create_mention_notifications_from_request(self, request, comment_id):
        data = request.data
        mentions = data.get("mentions", [])

        if not isinstance(mentions, list):
            return

        # Soft limit mentions to 10 users
        mentions = mentions[:10]
        if TESTING:
            celery_create_mention_notification(comment_id, mentions)
        else:
            celery_create_mention_notification.apply_async(
                (comment_id, mentions), countdown=1
            )

    def _create_thread_permission(self, user, thread, organization):
        data = {
            "access_type": ADMIN,
            "source": thread,
            "user": user,
            "organization": organization,
        }
        return Permission.objects.create(**data)

    def _retrieve_or_create_thread_from_request(self, request):
        data = request.data
        user = request.user
        organization = getattr(request, "organization", None)

        try:
            thread_id = data.get("thread_id", None)
            if thread_id is not None:
                thread = self._get_model_object_threads().get(id=thread_id)
                parent = thread.rh_comments.first()
                return thread, parent.id
            else:
                existing_thread, parent_id = self._get_existing_thread_from_request(
                    request
                )
                if existing_thread is not None:
                    return existing_thread, parent_id
                else:
                    thread_target_instance = self._get_model_object()
                    privacy_type = data.get("privacy_type", PUBLIC)
                    serializer = RhCommentThreadSerializer(
                        data={
                            "thread_type": data.get("thread_type", GENERIC_COMMENT),
                            "thread_reference": data.get("thread_reference", None),
                            "anchor": data.get("anchor", None),
                            "created_by": user.id,
                            "updated_by": user.id,
                            "content_type": ContentType.objects.get_for_model(
                                thread_target_instance
                            ).id,
                            "object_id": thread_target_instance.id,
                        }
                    )
                    serializer.is_valid(raise_exception=True)
                    instance = serializer.save()

                    return instance, None

        except Exception as error:
            raise Exception(f"Failed to create / retrieve rh_thread: {error}")

    def _get_existing_thread_from_request(self, request):
        data = request.data
        parent_id = data.get("parent_id", None)

        if parent_id:
            parent_comment = get_object_or_404(self.get_queryset(), pk=parent_id)
            thread = parent_comment.thread
            return thread, parent_comment.id
        return None, None
