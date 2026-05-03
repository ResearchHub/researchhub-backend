from django.db.models import Prefetch
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.constants import ExpertiseLevel, Gender, Region
from research_ai.models import ExpertSearch, SearchExpert
from research_ai.permissions import ResearchAIPermission
from research_ai.serializers import (
    ExpertSearchCreateSerializerV2,
    ExpertSearchDetailSerializerV2,
    ExpertSearchListItemSerializerV2,
)
from research_ai.services.expert_finder_service import get_document_content
from research_ai.tasks import run_expert_finder_search_v2
from research_ai.views.expert_finder_views import _get_document_title, _get_sse_url
from researchhub_document.models import ResearchhubUnifiedDocument
from user.permissions import IsModerator, UserIsEditor


def _v2_search_prefetch():
    return Prefetch(
        "search_experts",
        queryset=SearchExpert.objects.select_related("expert").order_by("position"),
    )


class ExpertSearchListCreateViewV2(APIView):
    """
    GET ``/expert-finder/v2/searches/`` — list searches (v2 payload shape).
    POST ``/expert-finder/v2/searches/`` — create and enqueue ``run_expert_finder_search_v2``.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def get_queryset(self):
        return (
            ExpertSearch.objects.select_related(
                "created_by",
                "created_by__author_profile",
            )
            .prefetch_related(_v2_search_prefetch())
            .order_by("-created_date")
        )

    def get(self, request):
        limit = max(1, min(100, int(request.query_params.get("limit", 10))))
        offset = max(0, int(request.query_params.get("offset", 0)))
        qs = self.get_queryset()
        total = qs.count()
        end = offset + limit
        items = list(qs[offset:end])
        ser = ExpertSearchListItemSerializerV2(items, many=True)
        return Response(
            {
                "searches": ser.data,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    def post(self, request):
        ser = ExpertSearchCreateSerializerV2(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        unified_document_id = data["unified_document_id"]
        additional_context = (data.get("additional_context") or "").strip()
        search_name = (data.get("name") or "").strip()
        input_type = data["input_type"]
        config = data.get("config") or {}
        excluded_search_ids = data.get("excluded_search_ids") or []

        search_config = {
            "expert_count": config.get("expert_count", 10),
            "expertise_level": config.get(
                "expertise_level", [ExpertiseLevel.ALL_LEVELS]
            ),
            "region": config.get("region", Region.ALL_REGIONS),
            "state": config.get("state", "All States"),
            "gender": config.get("gender", Gender.ALL_GENDERS),
        }

        try:
            unified_doc = ResearchhubUnifiedDocument.objects.get(id=unified_document_id)
        except ResearchhubUnifiedDocument.DoesNotExist:
            return Response(
                {"detail": "Unified document not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            query_text, content_type = get_document_content(unified_doc, input_type)
        except ValueError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        effective_input_type = content_type
        is_pdf = content_type == ExpertSearch.InputType.PDF
        if not search_name:
            search_name = _get_document_title(unified_doc)

        expert_search = ExpertSearch.objects.create(
            created_by=request.user,
            unified_document_id=unified_document_id,
            name=search_name,
            query=query_text,
            additional_context=additional_context,
            input_type=effective_input_type,
            config=search_config,
            excluded_expert_names=[],
            excluded_search_ids=excluded_search_ids,
            status=ExpertSearch.Status.PENDING,
            progress=0,
            current_step="Queued for processing (v2)",
        )

        search_id = expert_search.id
        run_expert_finder_search_v2.delay(
            search_id=str(search_id),
            query=query_text,
            config=search_config,
            excluded_search_ids=excluded_search_ids or None,
            is_pdf=is_pdf,
            additional_context=additional_context or None,
        )

        sse_url = _get_sse_url(request, str(search_id))
        return Response(
            {
                "search_id": search_id,
                "status": ExpertSearch.Status.PROCESSING,
                "message": "Expert search submitted for processing (v2)",
                "sse_url": sse_url,
            },
            status=status.HTTP_201_CREATED,
        )


class ExpertSearchDetailViewV2(APIView):
    """GET ``/expert-finder/v2/searches/<id>/`` — detail with relational ``experts``."""

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def get(self, request, search_id):
        try:
            expert_search = (
                ExpertSearch.objects.select_related(
                    "created_by",
                    "created_by__author_profile",
                )
                .prefetch_related(_v2_search_prefetch())
                .get(id=search_id)
            )
        except ExpertSearch.DoesNotExist:
            return Response(
                {"detail": "Expert search not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        ser = ExpertSearchDetailSerializerV2(
            expert_search, context={"request": request}
        )
        return Response(ser.data)
