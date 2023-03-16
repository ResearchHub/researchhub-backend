from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.query import QuerySet
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_comment.serializers import (
    DynamicRHCommentSerializer,
    DynamicRHThreadSerializer,
    RhCommentThreadSerializer,
)


class RhCommentThreadViewMixin:
    _ALLOWED_MODEL_NAMES = ("paper", "researchhub_post", "hypothesis", "citation")
    _MODEL_NAME_MAPPINGS = {
        "paper": ContentType.objects.get(model="paper"),
        "researchhub_post": ContentType.objects.get(model="researchhubpost"),
        "hypothesis": ContentType.objects.get(model="hypothesis"),
        "citation": ContentType.objects.get(model="citation"),
    }
    _THREAD_MIXIN_METHODS_ = (
        "create_rh_comment",
        "get_rh_comments",
    )

    def _get_model_threads(self):
        return self.get_object().rh_threads.all()

    def get_queryset(self):
        """
        Taken from DRF source code
        """
        assert self.queryset is not None, (
            "'%s' should either include a `queryset` attribute, "
            "or override the `get_queryset()` method." % self.__class__.__name__
        )

        # Custom logic start
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
        thread_queryset = model_object.rh_threads.values_list("id")
        queryset = RhCommentModel.objects.filter(thread__in=thread_queryset)
        # Custom logic end

        if isinstance(queryset, QuerySet):
            # Ensure queryset is re-evaluated on each request.
            queryset = queryset.all()
        return queryset

    def _get_retrieve_context(self):
        context = {
            "rhc_dts_get_comments": {"_exclude_fields": ("thread",)},
            "rhc_dcs_get_created_by": {
                "_include_fields": (
                    "id",
                    "author_profile",
                )
            },
            "usr_das_get_is_hub_editor_of": {"_include_fields": ("id", "name", "slug")},
            "usr_dus_get_author_profile": {
                "_include_fields": (
                    "id",
                    "first_name",
                    "last_name",
                    "created_date",
                    "updated_date",
                    "profile_image",
                    "is_hub_editor_of",
                )
            },
        }
        return context

    @action(detail=False, methods=["POST"], permission_classes=[IsAuthenticated])
    def create_rh_comment(self, request, model=None, object_id=None):
        try:
            rh_thread = self._retrieve_or_create_thread_from_request(request)
            _rh_comment = RhCommentModel.create_from_data(
                {**request.data, "user": request.user}, rh_thread
            )
            rh_thread.refresh_from_db()  # object update from fresh db values
            return Response(
                RhCommentThreadSerializer(instance=rh_thread).data, status=200
            )
        except Exception as error:
            return Response(
                f"Failed - create_rh_comment: {error}",
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(
        detail=True,
        methods=["GET"],
        permission_classes=[AllowAny],
    )
    # @action(detail=True, methods=["GET"], permission_classes=[AllowAny])
    def get_rh_comments(self, request, model=None, model_object_id=None, pk=None):
        # import pdb; pdb.set_trace()
        test = self._get_model_threads()
        # test = self._get_filtered_threads()
        try:
            # TODO: add filtering & sorting mechanism here.
            context = self._get_retrieve_context()
            comment = self._get_existing_thread_from_request(request)
            serializer = DynamicRHCommentSerializer(
                comment,
                context=context,
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
            serializer = DynamicRHCommentSerializer(
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
