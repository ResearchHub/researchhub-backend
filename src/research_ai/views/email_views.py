import logging

from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.constants import DEFAULT_EMAIL_TEMPLATE_KEY, VALID_EMAIL_TEMPLATE_KEYS
from research_ai.models import ExpertSearch, GeneratedEmail
from research_ai.permissions import ResearchAIPermission
from research_ai.serializers import (
    BulkGenerateEmailRequestSerializer,
    GeneratedEmailCreateUpdateSerializer,
    GeneratedEmailSerializer,
    GenerateEmailRequestSerializer,
    PreviewEmailRequestSerializer,
    SendEmailRequestSerializer,
)
from research_ai.services.email_generator_service import generate_expert_email
from research_ai.services.email_sending_service import send_plain_email
from research_ai.services.expert_display import (
    expert_name_for_generated_email_storage,
    expert_title_for_generated_email_storage,
)
from research_ai.services.expert_persist import mark_expert_last_email_sent_at
from research_ai.services.rfp_email_context import resolve_expert_from_search
from research_ai.tasks import process_bulk_generate_emails_task, send_queued_emails_task
from user.permissions import IsModerator, UserIsEditor

logger = logging.getLogger(__name__)


def _generated_email_list_sequence_queryset(expert_search_id):
    """
    Same default ordering and search scope as GET expert-finder/emails/:
    order by -created_date; if expert_search_id is not None, filter to that search
    (equivalent to ?search_id=<id>). If None, no expert_search filter (full list).
    """
    qs = GeneratedEmail.objects.order_by("-created_date")
    if expert_search_id is not None:
        qs = qs.filter(expert_search_id=expert_search_id)
    return qs


def _list_navigation_for_generated_email(email):
    """
    Adjacent rows in the same order as the paginated list for this email's search
    (or the unfiltered list when expert_search is null).
    """
    qs = _generated_email_list_sequence_queryset(email.expert_search_id)
    ids = list(qs.values_list("id", flat=True))
    try:
        idx = ids.index(email.id)
    except ValueError:
        return {
            "total": len(ids),
            "position": 1,
            "previous_id": None,
            "next_id": None,
        }
    n = len(ids)
    return {
        "total": n,
        "position": idx + 1,
        "previous_id": ids[idx - 1] if idx > 0 else None,
        "next_id": ids[idx + 1] if idx < n - 1 else None,
    }


def _generated_email_detail_response(email):
    data = GeneratedEmailSerializer(email).data
    data["list_navigation"] = _list_navigation_for_generated_email(email)
    return data


def _normalize_template(template: str) -> tuple[str, str | None]:
    """Return (template_key, custom_use_case or None). Supports 'custom: use case'."""
    template = (template or "").strip()
    if template.startswith("custom:"):
        return "custom", template[7:].strip() or None
    if template in VALID_EMAIL_TEMPLATE_KEYS:
        return template, None
    return "custom", template or None


def _resolve_generate_llm_params(request_data: dict, validated_data: dict):
    """
    Return (template_key, custom_use_case) for generate_expert_email.
    (None, None) means fixed template path (template was JSON null).
    """
    if "template" in request_data and request_data["template"] is None:
        return None, None
    raw = validated_data.get("template")
    if raw is None:
        return DEFAULT_EMAIL_TEMPLATE_KEY, None
    return _normalize_template(raw)


def _stored_template_for_bulk(request_data: dict, validated_data: dict) -> str | None:
    """Value persisted on GeneratedEmail.template for bulk jobs (null = fixed path)."""
    if "template" in request_data and request_data["template"] is None:
        return None
    raw = validated_data.get("template")
    if raw is None:
        return DEFAULT_EMAIL_TEMPLATE_KEY
    key, _ = _normalize_template(raw)
    return key


class GenerateEmailView(APIView):
    """POST /api/research_ai/expert-finder/generate-email/ - Generate outreach email via LLM and save as draft."""

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request):
        ser = GenerateEmailRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            expert_search = ExpertSearch.objects.get(id=data["expert_search_id"])
        except ExpertSearch.DoesNotExist:
            return Response(
                {"detail": "Expert search not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        resolved = resolve_expert_from_search(expert_search, data["expert_email"])
        if not resolved:
            return Response(
                {"detail": "Expert not found in search results for this email."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        template_key, custom_use_case = _resolve_generate_llm_params(request.data, data)
        template_id = data.get("template_id")

        try:
            subject, body = generate_expert_email(
                resolved_expert=resolved,
                template=template_key,
                custom_use_case=custom_use_case,
                expert_search=expert_search,
                template_id=template_id,
                user=request.user,
            )
        except ValueError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except RuntimeError as e:
            logger.exception("Email generation failed")
            return Response(
                {"detail": str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Optional: generate-only (no save) via query param save=false or action=generate
        save_param = request.query_params.get("save", "true").lower()
        action_param = request.query_params.get("action", "").lower()
        if save_param == "false" or action_param == "generate":
            return Response({"subject": subject, "body": body})

        stored_template = None if template_key is None else template_key
        email_record = GeneratedEmail.objects.create(
            created_by=request.user,
            expert_search=expert_search,
            expert_name=expert_name_for_generated_email_storage(resolved),
            expert_title=expert_title_for_generated_email_storage(resolved),
            expert_affiliation=resolved.get("affiliation") or "",
            expert_email=(resolved.get("email") or "").strip(),
            expertise=resolved.get("expertise") or "",
            email_subject=subject,
            email_body=body,
            template=stored_template,
            status="draft",
            notes=resolved.get("notes") or "",
        )

        out = GeneratedEmailSerializer(email_record)
        return Response(out.data, status=status.HTTP_201_CREATED)


class BulkGenerateEmailView(APIView):
    """POST /api/research_ai/expert-finder/generate-emails-bulk/ - Create placeholders and enqueue Celery task."""

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request):
        ser = BulkGenerateEmailRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            expert_search = ExpertSearch.objects.get(id=data["expert_search_id"])
        except ExpertSearch.DoesNotExist:
            return Response(
                {"detail": "Expert search not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        stored_template = _stored_template_for_bulk(request.data, data)
        placeholders = []
        try:
            with transaction.atomic():
                for item in data["experts"]:
                    resolved = resolve_expert_from_search(
                        expert_search, item["expert_email"]
                    )
                    if not resolved:
                        raise ValueError(
                            f"Expert not found in search results: {item['expert_email']}."
                        )
                    email_record = GeneratedEmail.objects.create(
                        created_by=request.user,
                        expert_search=expert_search,
                        expert_name=expert_name_for_generated_email_storage(resolved),
                        expert_title=expert_title_for_generated_email_storage(resolved),
                        expert_affiliation=resolved.get("affiliation") or "",
                        expert_email=(resolved.get("email") or "").strip(),
                        expertise=resolved.get("expertise") or "",
                        email_subject="",
                        email_body="",
                        template=stored_template,
                        status=GeneratedEmail.Status.PROCESSING,
                        notes=resolved.get("notes") or "",
                    )
                    placeholders.append(email_record)
        except ValueError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ids = [p.id for p in placeholders]
        process_bulk_generate_emails_task.delay(
            ids,
            template_id=data.get("template_id"),
            created_by_id=request.user.id,
        )

        out = GeneratedEmailSerializer(placeholders, many=True)
        return Response(
            {"emails": out.data, "ids": ids},
            status=status.HTTP_202_ACCEPTED,
        )


class PreviewEmailView(APIView):
    """POST /api/research_ai/expert-finder/emails/preview/ - Send generated email(s) to current user."""

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request):
        ser = PreviewEmailRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        recipient = (getattr(request.user, "email", None) or "").strip()
        if not recipient or "@" not in recipient:
            return Response(
                {"detail": "User has no email address for preview."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        get_full_name = getattr(request.user, "get_full_name", None)
        display_name = (
            (get_full_name() if callable(get_full_name) else "") or ""
        ).strip() or "ResearchHub"
        from_email = (
            f"{display_name} via ResearchHub <{settings.EXPERT_FINDER_FROM_EMAIL}>"
        )

        ids = data["generated_email_ids"]
        reply_to = (data["reply_to"] or "").strip()
        qs = GeneratedEmail.objects.filter(id__in=ids).exclude(
            status=GeneratedEmail.Status.PROCESSING
        )
        sent = 0
        for rec in qs:
            try:
                send_plain_email(
                    recipient,
                    rec.email_subject,
                    rec.email_body,
                    reply_to=reply_to,
                    from_email=from_email,
                )
                sent += 1
            except Exception as e:
                logger.exception("Preview send failed for email id=%s: %s", rec.id, e)
                return Response(
                    {"detail": str(e)},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
        return Response({"sent": sent})


class SendEmailView(APIView):
    """POST /api/research_ai/expert-finder/emails/send/ - Send generated emails to experts via SES."""

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request):
        ser = SendEmailRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        reply_to = (data["reply_to"] or "").strip()
        cc_list = list(data.get("cc") or [])
        ids = data["generated_email_ids"]

        get_full_name = getattr(request.user, "get_full_name", None)
        display_name = (
            (get_full_name() if callable(get_full_name) else "") or ""
        ).strip() or "ResearchHub"
        from_email = (
            f"{display_name} via ResearchHub <{settings.EXPERT_FINDER_FROM_EMAIL}>"
        )

        qs = GeneratedEmail.objects.filter(
            id__in=ids,
            status=GeneratedEmail.Status.DRAFT,
        )
        queued_ids = list(qs.values_list("id", flat=True))
        if queued_ids:
            GeneratedEmail.objects.filter(id__in=queued_ids).update(
                status=GeneratedEmail.Status.SENDING
            )
            send_queued_emails_task.delay(
                generated_email_ids=queued_ids,
                reply_to=reply_to,
                cc=cc_list,
                from_email=from_email,
            )
        return Response({"sent": len(queued_ids)})


class GeneratedEmailListView(APIView):
    """GET /api/research_ai/expert-finder/emails/ - List. POST - Create draft (no LLM)."""

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def get_queryset(self):
        return GeneratedEmail.objects.select_related(
            "created_by",
            "created_by__author_profile",
        ).order_by("-created_date")

    def get(self, request):
        limit = max(1, min(100, int(request.query_params.get("limit", 20))))
        offset = max(0, int(request.query_params.get("offset", 0)))
        qs = self.get_queryset()
        search_id = request.query_params.get("search_id")
        if search_id is not None:
            try:
                sid = int(search_id)
            except (ValueError, TypeError):
                qs = qs.none()
            else:
                qs = qs.filter(expert_search_id=sid)
        total = qs.count()
        items = list(qs[offset : offset + limit])
        ser = GeneratedEmailSerializer(items, many=True)
        return Response(
            {
                "emails": ser.data,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    def post(self, request):
        ser = GeneratedEmailCreateUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        data["created_by"] = request.user
        email = GeneratedEmail.objects.create(**data)
        out = GeneratedEmailSerializer(email)
        return Response(out.data, status=status.HTTP_201_CREATED)


class GeneratedEmailDetailView(APIView):
    """GET /api/research_ai/expert-finder/emails/<id>/ - Retrieve one. PATCH - Update. DELETE - Delete."""

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def _get_email(self, request, email_id):
        try:
            email = GeneratedEmail.objects.select_related(
                "created_by",
                "created_by__author_profile",
            ).get(id=int(email_id))
            return email, None
        except (ValueError, TypeError, GeneratedEmail.DoesNotExist):
            return None, Response(
                {"detail": "Generated email not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def get(self, request, email_id):
        email, err = self._get_email(request, email_id)
        if err:
            return err
        return Response(_generated_email_detail_response(email))

    def patch(self, request, email_id):
        email, err = self._get_email(request, email_id)
        if err:
            return err
        ser = GeneratedEmailCreateUpdateSerializer(
            email, data=request.data, partial=True
        )
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            old_status = email.status
            ser.save()
            if (
                old_status != GeneratedEmail.Status.SENT
                and email.status == GeneratedEmail.Status.SENT
            ):
                mark_expert_last_email_sent_at(email.expert_email)
        return Response(_generated_email_detail_response(email))

    def delete(self, request, email_id):
        email, err = self._get_email(request, email_id)
        if err:
            return err
        email.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
