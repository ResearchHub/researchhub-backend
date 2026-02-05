import json
import logging
from uuid import UUID

from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.models import ExpertSearch
from research_ai.permissions import ResearchAIPermission
from research_ai.serializers import (
    ExpertSearchCreateSerializer,
    ExpertSearchListItemSerializer,
    ExpertSearchSerializer,
)
from research_ai.services.expert_finder_service import get_document_content
from research_ai.services.progress_service import ProgressService, TaskType
from research_ai.tasks import process_expert_search_task
from researchhub_document.models import ResearchhubUnifiedDocument
from user.permissions import IsModerator

logger = logging.getLogger(__name__)


def _get_sse_url(request, search_id):
    if not request:
        return None
    base = request.build_absolute_uri("/").rstrip("/")
    return base + "/api/research_ai/expert-finder/progress/" + search_id + "/"


class ExpertSearchCreateView(APIView):
    permission_classes = [IsAuthenticated, ResearchAIPermission, IsModerator]

    def post(self, request):
        ser = ExpertSearchCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        unified_document_id = data.get("unified_document_id")
        query_text = (data.get("query") or "").strip()
        input_type = data.get("input_type", "abstract")
        config = data.get("config") or {}
        excluded_expert_names = data.get("excluded_expert_names") or []

        search_config = {
            "expert_count": config.get("expert_count", 10),
            "expertise_level": config.get("expertise_level", "All Levels"),
            "region": config.get("region", "All Regions"),
            "state": config.get("state", "All States"),
            "gender": config.get("gender", "All Genders"),
        }

        if unified_document_id:
            try:
                unified_doc = ResearchhubUnifiedDocument.objects.get(
                    id=unified_document_id
                )
            except ResearchhubUnifiedDocument.DoesNotExist:
                return Response(
                    {"detail": "Unified document not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            try:
                content_text, content_type = get_document_content(
                    unified_doc, input_type
                )
            except ValueError as e:
                return Response(
                    {"detail": str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            query_text = content_text
            effective_input_type = content_type
            is_pdf = content_type == "pdf"
        else:
            effective_input_type = "custom_query"
            is_pdf = False

        expert_search = ExpertSearch.objects.create(
            created_by=request.user,
            unified_document_id=unified_document_id or None,
            query=query_text,
            input_type=effective_input_type,
            config=search_config,
            excluded_expert_names=excluded_expert_names,
            status="pending",
            progress=0,
            current_step="Queued for processing",
        )

        search_id = str(expert_search.id)
        process_expert_search_task.delay(
            search_id=search_id,
            query=query_text,
            config=search_config,
            excluded_expert_names=(
                excluded_expert_names if excluded_expert_names else None
            ),
            is_pdf=is_pdf,
        )

        sse_url = _get_sse_url(request, search_id)
        return Response(
            {
                "search_id": expert_search.id,
                "status": "processing",
                "message": "Expert search submitted for processing",
                "sse_url": sse_url,
            },
            status=status.HTTP_201_CREATED,
        )


class ExpertSearchDetailView(APIView):
    permission_classes = [IsAuthenticated, ResearchAIPermission, IsModerator]

    def get(self, request, search_id):
        try:
            uuid_val = UUID(search_id)
        except ValueError:
            return Response(
                {"detail": "Invalid search ID."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            expert_search = ExpertSearch.objects.get(
                id=uuid_val, created_by=request.user
            )
        except ExpertSearch.DoesNotExist:
            return Response(
                {"detail": "Expert search not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        ser = ExpertSearchSerializer(expert_search)
        return Response(ser.data)


class ExpertSearchListView(APIView):
    permission_classes = [IsAuthenticated, ResearchAIPermission, IsModerator]

    def get_queryset(self):
        return ExpertSearch.objects.filter(created_by=self.request.user).order_by(
            "-created_date"
        )

    def get(self, request):
        limit = max(1, min(100, int(request.query_params.get("limit", 10))))
        offset = max(0, int(request.query_params.get("offset", 0)))
        qs = self.get_queryset()
        total = qs.count()
        end = offset + limit
        items = list(qs[offset:end])
        ser = ExpertSearchListItemSerializer(items, many=True)
        return Response(
            {
                "searches": ser.data,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )


def _final_progress_payload(search):
    """Build SSE progress payload from ExpertSearch for completed/failed state."""
    return {
        "status": search.status,
        "progress": search.progress,
        "currentStep": search.current_step or "",
        "task_type": "experts",
        "task_id": str(search.id),
    }


def _sse_event_stream(search_id):
    progress_service = ProgressService()
    yield "event: connected\n"
    payload = {
        "status": "connected",
        "task_type": "experts",
        "task_id": search_id,
    }
    yield "data: " + json.dumps(payload) + "\n\n"

    # If already completed/failed, return current state and close (no stuck)
    try:
        search = ExpertSearch.objects.filter(id=UUID(search_id)).first()
        if search and search.status in ("completed", "failed"):
            final = _final_progress_payload(search)
            if search.error_message:
                final["error"] = search.error_message
            yield "event: progress\n"
            yield "data: " + json.dumps(final) + "\n\n"
            yield "event: complete\n"
            yield "data: " + json.dumps({"status": "stream_complete"}) + "\n\n"
            return
    except (ValueError, Exception):
        pass

    # Subscribe to Redis; periodically re-check DB so we never wait forever
    none_count = 0
    db_check_interval = 10  # check DB every ~10 seconds when no Redis message

    for progress_data in progress_service.subscribe_to_progress_sync(
        TaskType.EXPERTS,
        search_id,
    ):
        if progress_data is None:
            none_count += 1
            if none_count >= db_check_interval:
                none_count = 0
                try:
                    search = ExpertSearch.objects.filter(id=UUID(search_id)).first()
                    if search and search.status in ("completed", "failed"):
                        final = _final_progress_payload(search)
                        if search.error_message:
                            final["error"] = search.error_message
                        yield "event: progress\n"
                        yield "data: " + json.dumps(final) + "\n\n"
                        yield "event: complete\n"
                        yield "data: " + json.dumps(
                            {"status": "stream_complete"}
                        ) + "\n\n"
                        return
                except (ValueError, Exception):
                    pass
            continue

        none_count = 0
        data_json = json.dumps(progress_data)
        yield "event: progress\n"
        yield "data: " + data_json + "\n\n"
        if progress_data.get("status") in ("completed", "failed"):
            yield "event: complete\n"
            yield "data: " + json.dumps({"status": "stream_complete"}) + "\n\n"
            return


class ExpertSearchProgressStreamView(APIView):
    permission_classes = [IsAuthenticated, ResearchAIPermission, IsModerator]

    def get(self, request, search_id):
        try:
            uuid_val = UUID(search_id)
        except ValueError:
            return Response(
                {"detail": "Invalid search ID."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            ExpertSearch.objects.get(id=uuid_val, created_by=request.user)
        except ExpertSearch.DoesNotExist:
            return Response(
                {"detail": "Expert search not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        response = StreamingHttpResponse(
            _sse_event_stream(search_id),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["Connection"] = "keep-alive"
        response["X-Accel-Buffering"] = "no"
        return response
