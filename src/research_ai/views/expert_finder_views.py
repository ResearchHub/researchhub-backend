import json
import logging

from django.http import StreamingHttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.constants import ExpertiseLevel, Gender, Region
from research_ai.models import Expert, ExpertSearch
from research_ai.permissions import ResearchAIPermission
from research_ai.serializers import (
    ExpertPartialUpdateSerializer,
    ExpertSearchCreateSerializer,
    ExpertSearchListItemSerializer,
    ExpertSearchSerializer,
    InvitedExpertSerializer,
    resolve_work_for_unified_document,
)
from research_ai.services.expert_display import expert_dict_to_api_payload
from research_ai.services.expert_finder_service import get_document_content
from research_ai.services.expert_results_payload import expert_model_to_flat_dict
from research_ai.services.invited_experts_service import get_document_invited_rows
from research_ai.services.progress_service import ProgressService, TaskType
from research_ai.tasks import process_expert_search_task
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


class ExpertSearchCreateView(APIView):
    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request):
        ser = ExpertSearchCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        unified_document_id = data.get("unified_document_id")
        query_text = (data.get("query") or "").strip()
        additional_context = (data.get("additional_context") or "").strip()
        search_name = (data.get("name") or "").strip()
        input_type = data.get("input_type")
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
            is_pdf = content_type == ExpertSearch.InputType.PDF
            if not search_name:
                search_name = _get_document_title(unified_doc)
        else:
            effective_input_type = ExpertSearch.InputType.CUSTOM_QUERY
            is_pdf = False

        expert_search = ExpertSearch.objects.create(
            created_by=request.user,
            unified_document_id=unified_document_id or None,
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
        process_expert_search_task.delay(
            search_id=str(search_id),
            query=query_text,
            config=search_config,
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


class ExpertFinderExpertDetailView(APIView):
    """
    PATCH a canonical Expert (name parts, email, affiliation, etc.).
    """

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
        ser = ExpertPartialUpdateSerializer(
            expert, data=request.data, partial=True, context={"request": request}
        )
        ser.is_valid(raise_exception=True)
        ser.save()
        payload = expert_dict_to_api_payload(
            expert_model_to_flat_dict(ser.instance),
            expert_id=ser.instance.id,
        )
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


INVITED_LIMIT = 20
INVITED_CACHE_SEC = 60 * 60 * 3  # 3 hours


class InvitedExpertsDocumentView(APIView):
    """
    GET experts tied to this document's searches who registered on RH (Expert.registered_user).
    Limit 20 rows, total_count for all matches. Response cached 3 hours.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    @method_decorator(cache_page(INVITED_CACHE_SEC))
    def get(self, request, unified_document_id):
        try:
            ResearchhubUnifiedDocument.objects.get(id=unified_document_id)
        except ResearchhubUnifiedDocument.DoesNotExist:
            return Response(
                {"detail": "Unified document not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        page, total_count = get_document_invited_rows(
            unified_document_id, limit=INVITED_LIMIT
        )
        invited_data = InvitedExpertSerializer(page, many=True).data
        return Response(
            {
                "unified_document_id": unified_document_id,
                "invited": invited_data,
                "total_count": total_count,
            }
        )


class ExpertSearchDetailView(APIView):
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
                .prefetch_related("search_experts__expert")
                .get(id=search_id)
            )
        except ExpertSearch.DoesNotExist:
            return Response(
                {"detail": "Expert search not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        ser = ExpertSearchSerializer(expert_search, context={"request": request})
        return Response(ser.data)


class ExpertSearchListView(APIView):
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
            .prefetch_related("search_experts__expert")
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

    # If already completed/failed, return current state and close (no stuck)
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

    # Subscribe to Redis; periodically re-check DB so we never wait forever
    none_count = 0
    db_check_interval = 10  # check DB every ~10 seconds when no Redis message

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
