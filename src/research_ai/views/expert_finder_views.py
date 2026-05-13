import json
import logging

from django.core.cache import cache
from django.db.models import Prefetch
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.constants import ExpertiseLevel, Gender, Region
from research_ai.models import Expert, ExpertSearch, SearchExpert
from research_ai.permissions import ResearchAIPermission
from research_ai.serializers import (
    ExpertSearchCreateSerializer,
    ExpertSearchDetailSerializer,
    ExpertSearchListItemSerializer,
    ExpertSerializer,
    ExpertUpdateSerializer,
    InvitedExpertOverviewQuerySerializer,
    InvitedExpertOverviewSerializer,
    resolve_work_for_unified_document,
)
from research_ai.services.expert_finder_service import get_document_content
from research_ai.services.invited_experts_service import get_invited_expert_overview
from research_ai.services.progress_service import ProgressService, TaskType
from research_ai.tasks import run_expert_finder_search
from researchhub_document.models import ResearchhubUnifiedDocument
from user.permissions import IsModerator, UserIsEditor

logger = logging.getLogger(__name__)


def _get_sse_url(request, search_id):
    if not request:
        return None
    base = request.build_absolute_uri("/").rstrip("/")
    return base + "/api/research_ai/expert-finder/progress/" + search_id + "/"


def _get_document_title(unified_doc):
    """Return a display title for the document (paper or post), max 512 chars."""
    try:
        doc = unified_doc.get_document()
        if doc is None:
            return ""
        if hasattr(doc, "display_title"):
            return (doc.display_title or "")[:512]
        if hasattr(doc, "title"):
            return (str(doc.title or ""))[:512]
        return ""
    except Exception:
        return ""


def _search_prefetch():
    return Prefetch(
        "search_experts",
        queryset=SearchExpert.objects.select_related("expert").order_by("position"),
    )


class ExpertSearchListCreateView(APIView):
    """
    GET ``/expert-finder/searches/`` — list searches.
    POST ``/expert-finder/searches/`` — create and enqueue expert finder task.
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
            .prefetch_related(_search_prefetch())
            .order_by("-created_date")
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

    def post(self, request):
        ser = ExpertSearchCreateSerializer(data=request.data)
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
            excluded_search_ids=excluded_search_ids,
            status=ExpertSearch.Status.PENDING,
            progress=0,
            current_step="Queued for processing",
        )

        search_id = expert_search.id
        run_expert_finder_search.delay(
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
                "message": "Expert search submitted for processing",
                "sse_url": sse_url,
            },
            status=status.HTTP_201_CREATED,
        )


class ExpertSearchDetailView(APIView):
    """GET ``/expert-finder/searches/<id>/`` — detail with relational ``experts``."""

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
                .prefetch_related(_search_prefetch())
                .get(id=search_id)
            )
        except ExpertSearch.DoesNotExist:
            return Response(
                {"detail": "Expert search not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        ser = ExpertSearchDetailSerializer(expert_search, context={"request": request})
        return Response(ser.data)


class ExpertDetailView(APIView):
    """PATCH ``/expert-finder/experts/<id>/`` — partial update on one expert."""

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def patch(self, request, expert_id):
        try:
            expert = Expert.objects.get(id=expert_id)
        except Expert.DoesNotExist:
            return Response(
                {"detail": "Expert not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        ser = ExpertUpdateSerializer(expert, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ExpertSerializer(expert).data)


INVITED_OVERVIEW_CACHE_TTL = 60 * 60 * 1  # 1 hour


class InvitedExpertOverviewView(APIView):
    """
    GET ``/expert-finder/invited-experts/overview/``.

    Aggregates invited experts and generated-email metrics for ``ExpertSearch`` rows,
    optionally scoped by unified document and ``created_date`` (calendar-day bounds).
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    @staticmethod
    def _cache_key(*, unified_document_id, start, end):
        ud_part = (
            str(int(unified_document_id)) if unified_document_id is not None else "none"
        )
        start_part = start.isoformat() if start is not None else "none"
        end_part = end.isoformat() if end is not None else "none"
        return f"invited_expert_overview:ud={ud_part}:start={start_part}:end={end_part}"

    def get(self, request):
        qser = InvitedExpertOverviewQuerySerializer(data=request.query_params)
        qser.is_valid(raise_exception=True)
        params = qser.validated_data
        unified_document_id = params.get("unified_document_id")
        start = params.get("start")
        end = params.get("end")

        if unified_document_id is not None:
            try:
                ResearchhubUnifiedDocument.objects.get(id=unified_document_id)
            except ResearchhubUnifiedDocument.DoesNotExist:
                return Response(
                    {"detail": "Unified document not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        cache_key = self._cache_key(
            unified_document_id=unified_document_id,
            start=start,
            end=end,
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        overview = get_invited_expert_overview(
            unified_document_id=unified_document_id,
            start=start,
            end=end,
        )
        response_data = InvitedExpertOverviewSerializer(overview).data
        payload = {
            **response_data,
            "meta": {"cached_at": timezone.now().isoformat()},
        }
        cache.set(cache_key, payload, INVITED_OVERVIEW_CACHE_TTL)
        return Response(payload)


class ExpertSearchWorkView(APIView):
    """
    GET work (paper or post) for a unified document by ID.
    Returns {"work": <payload>} or {"work": null} if not resolvable.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def get(self, request, unified_document_id):
        try:
            unified_doc = ResearchhubUnifiedDocument.objects.get(id=unified_document_id)
        except ResearchhubUnifiedDocument.DoesNotExist:
            return Response(
                {"detail": "Unified document not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        work = resolve_work_for_unified_document(
            unified_doc, context={"request": request}
        )
        return Response({"work": work})


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
    try:
        search_id_int = int(search_id)
    except (ValueError, TypeError):
        search_id_int = None

    yield "event: connected\n"
    payload = {
        "status": "connected",
        "task_type": "experts",
        "task_id": search_id,
    }
    yield "data: " + json.dumps(payload) + "\n\n"

    if search_id_int is not None:
        try:
            search = ExpertSearch.objects.filter(id=search_id_int).first()
            if search and search.status in (
                ExpertSearch.Status.COMPLETED,
                ExpertSearch.Status.FAILED,
            ):
                final = _final_progress_payload(search)
                if search.error_message:
                    final["error"] = search.error_message
                yield "event: progress\n"
                yield "data: " + json.dumps(final) + "\n\n"
                yield "event: complete\n"
                yield "data: " + json.dumps({"status": "stream_complete"}) + "\n\n"
                return
        except Exception:
            pass

    none_count = 0
    db_check_interval = 10

    for progress_data in progress_service.subscribe_to_progress_sync(
        TaskType.EXPERTS,
        search_id,
    ):
        if progress_data is None:
            none_count += 1
            if none_count >= db_check_interval and search_id_int is not None:
                none_count = 0
                try:
                    search = ExpertSearch.objects.filter(id=search_id_int).first()
                    if search and search.status in (
                        ExpertSearch.Status.COMPLETED,
                        ExpertSearch.Status.FAILED,
                    ):
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
        if progress_data.get("status") in (
            ExpertSearch.Status.COMPLETED,
            ExpertSearch.Status.FAILED,
        ):
            yield "event: complete\n"
            yield "data: " + json.dumps({"status": "stream_complete"}) + "\n\n"
            return


class ExpertSearchProgressStreamView(APIView):
    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def get(self, request, search_id):
        try:
            ExpertSearch.objects.select_related("created_by").get(id=search_id)
        except ExpertSearch.DoesNotExist:
            return Response(
                {"detail": "Expert search not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        response = StreamingHttpResponse(
            _sse_event_stream(str(search_id)),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["Connection"] = "keep-alive"
        response["X-Accel-Buffering"] = "no"
        return response
