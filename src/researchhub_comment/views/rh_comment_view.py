from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.query import QuerySet
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from analytics.amplitude import track_event
from discussion.reaction_views import ReactionViewActionMixin
from researchhub.pagination import FasterDjangoPaginator
from researchhub.permissions import IsObjectOwner
from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT
from researchhub_comment.filters import RHCommentFilter
from researchhub_comment.models import RhCommentModel
from researchhub_comment.serializers import (
    DynamicRhCommentSerializer,
    RhCommentSerializer,
    RhCommentThreadSerializer,
)


class CursorSetPagination(CursorPagination):
    page_size = 20
    cursor_query_param = "page"
    ordering = "-created_date"


class CommentPagination(PageNumberPagination):
    django_paginator_class = FasterDjangoPaginator
    page_size_query_param = "page_size"
    max_page_size = 20
    page_size = 20


class RhCommentViewSet(ReactionViewActionMixin, ModelViewSet):
    queryset = RhCommentModel.objects.all()
    serializer_class = RhCommentSerializer
    filter_backends = (DjangoFilterBackend,)
    filter_class = RHCommentFilter
    pagination_class = CommentPagination
    permission_classes = [IsAuthenticatedOrReadOnly, IsObjectOwner]
    _ALLOWED_MODEL_NAMES = ("paper", "researchhub_post", "hypothesis", "citation")
    _CONTENT_TYPE_MAPPINGS = {
        "paper": "paper",
        "researchhub_post": "researchhubpost",
        "hypothesis": "hypothesis",
        "citation": "citation",
    }
    _ALLOWED_UPDATE_FIELDS = set(
        ["comment_content_type", "comment_content_json", "context_title"]
    )

    def _get_content_type_model(self, model_name):
        key = self._CONTENT_TYPE_MAPPINGS[model_name]
        content_type = ContentType.objects.get(model=key)
        return content_type

    def _get_model_object(self):
        kwargs = self.kwargs
        model_name = kwargs.get("model")
        model_object_id = kwargs.get("model_object_id")

        assert (
            model_object_id is not None
            and model_name is not None
            and model_name in self._ALLOWED_MODEL_NAMES
        ), f"{model_name} is not an accepted model"

        model = self._get_content_type_model(model_name).model_class()
        model_object = model.objects.get(id=model_object_id)
        return model_object

    def _get_model_object_threads(self):
        model_object = self._get_model_object()
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
            "rhc_dcs_get_thread": {"_include_fields": ("thread_type",)},
            "rhc_dcs_get_created_by": {
                "_include_fields": (
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                    "editor_of",
                )
            },
            "rhc_dcs_get_children": {
                "_exclude_fields": (
                    "thread",
                    "comment_content_src",
                    "promoted",
                    "user_endorsement",
                    "user_flag",
                )
            },
            "rhc_dcs_get_purchases": {"_include_fields": ("amount", "user")},
            "usr_dus_get_author_profile": {
                "_include_fields": (
                    "id",
                    "first_name",
                    "last_name",
                    "created_date",
                    "updated_date",
                    "profile_image",
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

    @track_event
    @action(
        detail=False, methods=["POST"], permission_classes=[IsAuthenticatedOrReadOnly]
    )
    def create_rh_comment(self, request, *args, **kwargs):
        data = request.data
        user = request.user
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
            self.add_upvote(user, rh_comment)
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
        queryset = self.filter_queryset(self.get_queryset().filter(parent__isnull=True))
        queryset = queryset.select_related(
            "created_by",
            "created_by__author_profile",
            "thread",
        )
        queryset = queryset.prefetch_related(
            "children",
            "purchases",
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
                "comment_content_src",
            ),
        )
        return Response(serializer.data)

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

        # This prevents users from changing important fields, e.g., parent or id
        disallowed_keys = set(data.keys()) - self._ALLOWED_UPDATE_FIELDS
        for key in disallowed_keys:
            data.pop(key)
        res = super().update(request, *args, **kwargs)
        context = self._get_retrieve_context()
        serializer_data = DynamicRhCommentSerializer(
            self.get_object(),
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
        methods=["GET"],
        permission_classes=[AllowAny],
    )
    # @action(detail=True, methods=["GET"], permission_classes=[AllowAny])
    def get_rh_comments(self, request, model=None, model_object_id=None, pk=None):
        # import pdb; pdb.set_trace()
        # test = self._get_filtered_threads()
        try:
            # TODO: add filtering & sorting mechanism here.
            comment = self._get_existing_thread_from_data(request.data)
            serializer = self.get_serializer(
                comment,
                _include_fields=("id", "comments"),
            )
            return Response(serializer.data, status=200)
        except Exception as error:
            return Response(
                f"Failed - get_comment_threads: {error}",
                status=status.HTTP_400_BAD_REQUEST,
            )

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

    def _retrieve_or_create_thread_from_request(self, request):
        data = request.data
        user = request.user

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
                    serializer = RhCommentThreadSerializer(
                        data={
                            "thread_type": data.get("thread_type", GENERIC_COMMENT),
                            "thread_reference": data.get("thread_reference", None),
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
