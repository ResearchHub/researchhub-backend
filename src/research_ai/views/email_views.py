"""
Expert finder email generation and CRUD API.
"""

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.constants import VALID_EMAIL_TEMPLATE_KEYS
from research_ai.models import ExpertSearch, GeneratedEmail
from research_ai.permissions import ResearchAIPermission
from research_ai.services.email_template_service import get_template as get_email_template
from research_ai.serializers import (
    GenerateEmailRequestSerializer,
    GeneratedEmailCreateUpdateSerializer,
    GeneratedEmailSerializer,
)
from research_ai.services.email_generator_service import generate_expert_email
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

        expert_name = (data.get("expert_name") or "").strip()
        if not expert_name:
            return Response(
                {"detail": "expert_name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        template_key, custom_use_case = _normalize_template(data.get("template") or "")

        # Resolve outreach_context and template_data (from request or template_id)
        outreach_context = (data.get("outreach_context") or "").strip() or None
        template_data = data.get("template_data")
        template_id = data.get("template_id")
        if template_id and not template_data:
            et = get_email_template(request.user, template_id)
            if et:
                outreach_context = outreach_context or (et.outreach_context or "").strip() or None
                template_data = {
                    "contact_name": et.contact_name or "",
                    "contact_title": et.contact_title or "",
                    "contact_institution": et.contact_institution or "",
                    "contact_email": et.contact_email or "",
                    "contact_phone": et.contact_phone or "",
                    "contact_website": et.contact_website or "",
                }

        try:
            subject, body = generate_expert_email(
                expert_name=expert_name,
                expert_title=data.get("expert_title") or "",
                expert_affiliation=data.get("expert_affiliation") or "",
                expertise=data.get("expertise") or "",
                notes=data.get("notes") or "",
                template=template_key,
                custom_use_case=custom_use_case,
                outreach_context=outreach_context,
                template_data=template_data,
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

        expert_search_id = data.get("expert_search_id")
        expert_search = None
        if expert_search_id:
            try:
                expert_search = ExpertSearch.objects.get(
                    id=expert_search_id, created_by=request.user
                )
            except ExpertSearch.DoesNotExist:
                pass

        email_record = GeneratedEmail.objects.create(
            created_by=request.user,
            expert_search=expert_search,
            expert_name=expert_name,
            expert_title=data.get("expert_title") or "",
            expert_affiliation=data.get("expert_affiliation") or "",
            expert_email=data.get("expert_email") or "",
            expertise=data.get("expertise") or "",
            email_subject=subject,
            email_body=body,
            template=template_key,
            status="draft",
            notes=data.get("notes") or "",
        )

        out = GeneratedEmailSerializer(email_record)
        return Response(out.data, status=status.HTTP_201_CREATED)


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
            email = GeneratedEmail.objects.get(id=int(email_id), created_by=request.user)
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


