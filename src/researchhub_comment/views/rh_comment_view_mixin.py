from django.contrib.contenttypes.models import ContentType
from django.db.models.query import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from analytics.amplitude import track_event
from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_comment.serializers import (
    DynamicRhCommentSerializer,
    RhCommentSerializer,
    RhCommentThreadSerializer,
)
from user.serializers import DynamicUserSerializer


class RhCommentViewMixin:
    _ALLOWED_MODEL_NAMES = ("paper", "researchhub_post", "hypothesis", "citation")
    _MODEL_NAME_MAPPINGS = {
        "paper": ContentType.objects.get(model="paper"),
        "researchhub_post": ContentType.objects.get(model="researchhubpost"),
        "hypothesis": ContentType.objects.get(model="hypothesis"),
        "citation": ContentType.objects.get(model="citation"),
    }

    def _get_model_object(self):
        kwargs = self.kwargs
        model_name = kwargs.get("model")
        model_object_id = kwargs.get("model_object_id")

        assert (
            model_object_id is not None
            and model_name is not None
            and model_name in self._ALLOWED_MODEL_NAMES
        ), f"{model_name} is not an accepted model"

        model = self._MODEL_NAME_MAPPINGS[model_name].model_class()
        model_object = model.objects.get(id=model_object_id)
        return model_object

    def get_queryset(self):
        """
        Taken from DRF source code
        """
        assert self.queryset is not None, (
            "'%s' should either include a `queryset` attribute, "
            "or override the `get_queryset()` method." % self.__class__.__name__
        )

        # Custom logic start
        model_object = self._get_model_object()
        thread_queryset = model_object.rh_threads.values_list("id")
        queryset = RhCommentModel.objects.filter(thread__in=thread_queryset)
        # Custom logic end

        if isinstance(queryset, QuerySet):
            # Ensure queryset is re-evaluated on each request.
            queryset = queryset.all()
        return queryset

    def get_serializer_class(self):
        if self.action == "create_rh_comment":
            return super().get_serializer_class()
        return DynamicRhCommentSerializer

    def _get_retrieve_context(self):
        context = {
            "rhc_dcs_get_created_by": {
                "_include_fields": ("id", "author_profile", "editor_of")
            },
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
        }
        return context

    @track_event
    @action(detail=False, methods=["POST"], permission_classes=[IsAuthenticated])
    def create_rh_comment(self, request, *args, **kwargs):
        data = request.data
        user = request.user
        rh_thread = self._retrieve_or_create_thread_from_request(request)
        comment_data = {
            **data,
            "created_by": user.id,
            "updated_by": user.id,
            "thread": rh_thread.id,
        }
        rh_comment, serializer_data = RhCommentModel.create_from_data(comment_data)
        context = self._get_retrieve_context()
        user_serializer = DynamicUserSerializer(
            user, _include_fields=("id", "author_profile"), context=context
        )
        serializer_data["created_by"] = user_serializer.data
        return Response(serializer_data, status=200)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        context = self._get_retrieve_context()
        if page is not None:
            serializer = self.get_serializer(
                page,
                many=True,
                context=context,
                _exclude_fields=("thread", "comment_content_src"),
            )
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(
            page,
            many=True,
            context=context,
            _exclude_fields=("thread", "comment_content_src"),
        )
        return Response(serializer.data)

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
                _exclude_fields=("thread", "comment_content_src"),
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
                return RhCommentThreadModel.objects.get(id=thread_id)
            else:
                existing_thread = self._get_existing_thread_from_request(request)
                if existing_thread is not None:
                    return existing_thread
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
                    return instance

        except Exception as error:
            raise Exception(f"Failed to create / retrieve rh_thread: {error}")

    def _get_existing_thread_from_request(self, request):
        data = request.data
        parent_id = data.get("parent_id", None)

        if parent_id:
            parent_comment = get_object_or_404(RhCommentModel, pk=parent_id)
            thread = parent_comment.thread
            return thread
        return None
