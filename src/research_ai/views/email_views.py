import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.utils.html import strip_tags
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.constants import VALID_EMAIL_TEMPLATE_KEYS
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
from research_ai.services.rfp_email_context import resolve_expert_from_search
from research_ai.tasks import process_bulk_generate_emails_task, send_queued_emails_task
from user.permissions import IsModerator

logger = logging.getLogger(__name__)


def _normalize_template(template: str) -> tuple[str, str | None]:
    """Return (template_key, custom_use_case or None). Supports 'custom: use case'."""
    template = (template or "").strip()
    if template.startswith("custom:"):
        return "custom", template[7:].strip() or None
    if template in VALID_EMAIL_TEMPLATE_KEYS:
        return template, None
    return "custom", template or None


class GenerateEmailView(APIView):
    """POST /api/research_ai/expert-finder/generate-email/ - Generate outreach email via LLM and save as draft."""

    permission_classes = [IsAuthenticated, ResearchAIPermission, IsModerator]

    def post(self, request):
        ser = GenerateEmailRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            expert_search = ExpertSearch.objects.get(
                id=data["expert_search_id"], created_by=request.user
            )
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

        template_key, custom_use_case = _normalize_template(data.get("template") or "")
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

        email_record = GeneratedEmail.objects.create(
            created_by=request.user,
            expert_search=expert_search,
            expert_name=(resolved.get("name") or "").strip(),
            expert_title=resolved.get("title") or "",
            expert_affiliation=resolved.get("affiliation") or "",
            expert_email=(resolved.get("email") or "").strip(),
            expertise=resolved.get("expertise") or "",
            email_subject=subject,
            email_body=body,
            template=template_key,
            status="draft",
            notes=resolved.get("notes") or "",
        )

        out = GeneratedEmailSerializer(email_record)
        return Response(out.data, status=status.HTTP_201_CREATED)


class BulkGenerateEmailView(APIView):
    """POST /api/research_ai/expert-finder/generate-emails-bulk/ - Create placeholders and enqueue Celery task."""

    permission_classes = [IsAuthenticated, ResearchAIPermission, IsModerator]

    def post(self, request):
        ser = BulkGenerateEmailRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            expert_search = ExpertSearch.objects.get(
                id=data["expert_search_id"], created_by=request.user
            )
        except ExpertSearch.DoesNotExist:
            return Response(
                {"detail": "Expert search not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        template_key, _ = _normalize_template(data.get("template") or "")
        placeholders = []
        for item in data["experts"]:
            resolved = resolve_expert_from_search(expert_search, item["expert_email"])
            if not resolved:
                return Response(
                    {
                        "detail": f"Expert not found in search results: {item['expert_email']}."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            email_record = GeneratedEmail.objects.create(
                created_by=request.user,
                expert_search=expert_search,
                expert_name=(resolved.get("name") or "").strip(),
                expert_title=resolved.get("title") or "",
                expert_affiliation=resolved.get("affiliation") or "",
                expert_email=(resolved.get("email") or "").strip(),
                expertise=resolved.get("expertise") or "",
                email_subject="",
                email_body="",
                template=template_key,
                status=GeneratedEmail.Status.PROCESSING,
                notes=resolved.get("notes") or "",
            )
            placeholders.append(email_record)

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


def _send_plain_email(to_emails, subject, body, reply_to=None, cc=None, from_email=None):
    """Send email via Django (SES backend). Body is sent as HTML with a plain-text fallback."""
    subject = (subject or "").replace("\n", "").replace("\r", "")
    if not settings.PRODUCTION:
        subject = "[Staging] " + subject
    if from_email is None:
        from_email = f"ResearchHub <{settings.DEFAULT_FROM_EMAIL}>"
    to_list = to_emails if isinstance(to_emails, list) else [to_emails]
    html_body = body or ""
    plain_body = strip_tags(html_body).strip() or "(No content)"

    if reply_to or cc:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=plain_body,
            from_email=from_email,
            to=to_list,
            reply_to=[reply_to] if reply_to else None,
            cc=cc or None,
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
    else:
        for to in to_list:
            try:
                send_mail(
                    subject,
                    plain_body,
                    from_email,
                    [to],
                    fail_silently=False,
                    html_message=html_body,
                )
            except Exception as e:
                logger.exception("Send email failed to %s: %s", to, e)
                raise


class PreviewEmailView(APIView):
    """POST /api/research_ai/expert-finder/emails/preview/ - Send generated email(s) to current user."""

    permission_classes = [IsAuthenticated, ResearchAIPermission, IsModerator]

    def post(self, request):
        ser = PreviewEmailRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        recipient = getattr(request.user, "email", None) or (
            request.user.username if hasattr(request.user, "username") else None
        )
        if not recipient:
            return Response(
                {"detail": "User has no email address for preview."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ids = data["generated_email_ids"]
        qs = GeneratedEmail.objects.filter(
            id__in=ids,
            created_by=request.user,
        ).exclude(status=GeneratedEmail.Status.PROCESSING)
        sent = 0
        for rec in qs:
            try:
                _send_plain_email(
                    [recipient],
                    rec.email_subject,
                    rec.email_body,
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

    permission_classes = [IsAuthenticated, ResearchAIPermission, IsModerator]

    def post(self, request):
        if not settings.PRODUCTION and not settings.TESTING:
            return Response(
                {"detail": "Sending emails to experts is disabled in non-production."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ser = SendEmailRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        reply_to = (data.get("reply_to") or "").strip() or None
        cc_list = list(data.get("cc") or [])
        use_noreply = data.get("use_noreply", False)
        ids = data["generated_email_ids"]

        if use_noreply:
            from_email = f"ResearchHub <{settings.DEFAULT_FROM_EMAIL}>"
        else:
            user_email = getattr(request.user, "email", None) or ""
            if not (user_email and "@" in user_email):
                return Response(
                    {
                        "detail": "User has no email address. Use use_noreply to send from ResearchHub."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            display_name = (
                getattr(request.user, "get_full_name", lambda: "")() or ""
            ).strip() or "ResearchHub"
            from_email = f"{display_name} <{user_email}>"

        qs = GeneratedEmail.objects.filter(
            id__in=ids,
            created_by=request.user,
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

    permission_classes = [IsAuthenticated, ResearchAIPermission, IsModerator]

    def get_queryset(self):
        return GeneratedEmail.objects.filter(created_by=self.request.user).order_by(
            "-created_date"
        )

    def get(self, request):
        limit = max(1, min(100, int(request.query_params.get("limit", 20))))
        offset = max(0, int(request.query_params.get("offset", 0)))
        qs = self.get_queryset()
        search_id = request.query_params.get("search_id")
        if search_id is not None:
            try:
                qs = qs.filter(expert_search_id=int(search_id))
            except (ValueError, TypeError):
                qs = qs.none()
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

    permission_classes = [IsAuthenticated, ResearchAIPermission, IsModerator]

    def _get_email(self, request, email_id):
        try:
            email = GeneratedEmail.objects.get(
                id=int(email_id), created_by=request.user
            )
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
        ser = GeneratedEmailSerializer(email)
        return Response(ser.data)

    def patch(self, request, email_id):
        email, err = self._get_email(request, email_id)
        if err:
            return err
        ser = GeneratedEmailCreateUpdateSerializer(
            email, data=request.data, partial=True
        )
        ser.is_valid(raise_exception=True)
        ser.save()
        out = GeneratedEmailSerializer(email)
        return Response(out.data)

    def delete(self, request, email_id):
        email, err = self._get_email(request, email_id)
        if err:
            return err
        email.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
