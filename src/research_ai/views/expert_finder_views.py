import json
import logging

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Max, Prefetch
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
    InvitedExpertEditorRowSerializer,
    InvitedExpertEditorsOverviewQuerySerializer,
    InvitedExpertOverviewQuerySerializer,
    InvitedExpertOverviewSerializer,
    InvitedExpertOverviewSummarySerializer,
    ManualExpertCreateSerializer,
    _get_user_with_author_payload,
    resolve_work_for_unified_document,
)
from research_ai.services.expert_finder_service import get_document_content
from research_ai.services.expert_persist import ExpertPersist
from research_ai.services.invited_experts_service import (
    get_invited_expert_editors_overview,
    get_invited_expert_overview,
    invited_stats_cache_key,
    load_editor_users,
)
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


class ExpertSearchAddExpertView(APIView):
    """POST ``/expert-finder/searches/<search_id>/experts/`` — manually add an expert.

    Upserts the canonical ``Expert`` (one row per email) and links it to the
    given ``ExpertSearch`` via a new ``SearchExpert`` row appended at the end
    of the existing ordering.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request, search_id):
        try:
            expert_search = ExpertSearch.objects.get(id=search_id)
        except ExpertSearch.DoesNotExist:
            return Response(
                {"detail": "Expert search not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        ser = ManualExpertCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            with transaction.atomic():
                expert = ExpertPersist.upsert_from_parsed_dict(data)
                ExpertPersist.tag_manual_source(expert, request.user)
                max_position = SearchExpert.objects.filter(
                    expert_search_id=expert_search.id
                ).aggregate(Max("position"))["position__max"]
                next_position = (max_position if max_position is not None else -1) + 1
                SearchExpert.objects.create(
                    expert_search_id=expert_search.id,
                    expert_id=expert.id,
                    position=next_position,
                )
        except IntegrityError:
            return Response(
                {"detail": "This expert is already in this search."},
                status=status.HTTP_409_CONFLICT,
            )
        except ValueError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            ExpertSerializer(expert).data,
            status=status.HTTP_201_CREATED,
        )


INVITED_OVERVIEW_CACHE_TTL = 60 * 60 * 1  # 1 hour
INVITED_STATS_CACHE_TTL = 60 * 60 * 1  # 1 hour


def _invited_stats_filters_meta(*, unified_document_id, start, end, editor_id=None):
    filters = {
        "unified_document_id": unified_document_id,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
    }
    if editor_id is not None:
        filters["editor_id"] = editor_id
    return filters


class InvitedExpertStatsMixin:
    """Shared cache helpers for invited-expert stats endpoints."""

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    cache_prefix = ""

    def _get_cached_or_build(self, *, cache_key, build_payload):
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        payload = build_payload()
        cache.set(cache_key, payload, INVITED_STATS_CACHE_TTL)
        return Response(payload)

    def _editor_items_payload(self, editors_overview):
        user_ids = [row.user_id for row in editors_overview.items]
        editor_users = load_editor_users(user_ids)
        items = []
        for row in editors_overview.items:
            user = editor_users.get(row.user_id)
            items.append(
                {
                    "editor": _get_user_with_author_payload(user),
                    "searches_total": row.searches_total,
                    "searches_completed": row.searches_completed,
                    "experts_total": row.experts_total,
                    "experts_signed_up": row.experts_signed_up,
                    "emails_generated": row.emails_generated,
                    "emails_sent": row.emails_sent,
                    "emails_opened": row.emails_opened,
                    "emails_bounced": row.emails_bounced,
                    "proposals_outreach_count": row.proposals_outreach_count,
                    "emails_sent_by_proposal": row.emails_sent_by_proposal,
                    "signup_rate": row.signup_rate,
                    "open_rate": row.open_rate,
                    "bounce_rate": row.bounce_rate,
                }
            )
        return {
            "items": InvitedExpertEditorRowSerializer(items, many=True).data,
            "total": editors_overview.total,
            "limit": editors_overview.limit,
            "offset": editors_overview.offset,
            "sort_by": editors_overview.sort_by,
            "sort_order": editors_overview.sort_order,
        }


class InvitedExpertOverviewView(InvitedExpertStatsMixin, APIView):
    """
    GET ``/expert-finder/invited-experts/overview/``.
    """

    cache_prefix = "overview"

    def get(self, request):
        qser = InvitedExpertOverviewQuerySerializer(data=request.query_params)
        qser.is_valid(raise_exception=True)
        params = qser.validated_data
        unified_document_id = params.get("unified_document_id")
        start = params.get("start")
        end = params.get("end")
        editor_id = params.get("editor_id")

        cache_key = invited_stats_cache_key(
            self.cache_prefix,
            ud=(
                str(int(unified_document_id))
                if unified_document_id is not None
                else "none"
            ),
            start=start.isoformat() if start is not None else "none",
            end=end.isoformat() if end is not None else "none",
            editor_id=editor_id if editor_id is not None else "none",
        )

        def build_payload():
            result = get_invited_expert_overview(
                unified_document_id=unified_document_id,
                start=start,
                end=end,
                editor_id=editor_id,
            )
            counts_data = InvitedExpertOverviewSerializer(result.counts).data
            summary_data = InvitedExpertOverviewSummarySerializer(result.summary).data
            return {
                **counts_data,
                "summary": summary_data,
                "meta": {
                    "cached_at": timezone.now().isoformat(),
                    "filters": _invited_stats_filters_meta(
                        unified_document_id=unified_document_id,
                        start=start,
                        end=end,
                        editor_id=editor_id,
                    ),
                },
            }

        return self._get_cached_or_build(
            cache_key=cache_key, build_payload=build_payload
        )


class InvitedExpertEditorsOverviewView(InvitedExpertStatsMixin, APIView):
    """
    GET ``/expert-finder/invited-experts/editors-overview/``.

    Paginated per-editor outreach metrics for the date/document window.
    """

    cache_prefix = "editors_overview"

    def get(self, request):
        qser = InvitedExpertEditorsOverviewQuerySerializer(data=request.query_params)
        qser.is_valid(raise_exception=True)
        params = qser.validated_data
        unified_document_id = params.get("unified_document_id")
        start = params.get("start")
        end = params.get("end")
        limit = params.get("limit", 5)
        offset = params.get("offset", 0)
        sort_by = params.get("sort_by", "experts_total")
        sort_order = params.get("sort_order", "desc")
        min_searches = params.get("min_searches", 1)

        cache_key = invited_stats_cache_key(
            self.cache_prefix,
            ud=(
                str(int(unified_document_id))
                if unified_document_id is not None
                else "none"
            ),
            start=start.isoformat() if start is not None else "none",
            end=end.isoformat() if end is not None else "none",
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
            min_searches=min_searches,
        )

        def build_payload():
            overview = get_invited_expert_editors_overview(
                unified_document_id=unified_document_id,
                start=start,
                end=end,
                limit=limit,
                offset=offset,
                sort_by=sort_by,
                sort_order=sort_order,
                min_searches=min_searches,
            )
            body = self._editor_items_payload(overview)
            return {
                **body,
                "meta": {
                    "cached_at": timezone.now().isoformat(),
                    "filters": _invited_stats_filters_meta(
                        unified_document_id=unified_document_id,
                        start=start,
                        end=end,
                    ),
                },
            }

        return self._get_cached_or_build(
            cache_key=cache_key, build_payload=build_payload
        )


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
                        yield (
                            "data: "
                            + json.dumps({"status": "stream_complete"})
                            + "\n\n"
                        )
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
