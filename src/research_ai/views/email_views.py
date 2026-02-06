"""
Expert finder email generation and CRUD API.
"""

import logging
from uuid import UUID

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.models import ExpertSearch, GeneratedEmail
from research_ai.permissions import ResearchAIPermission
from research_ai.serializers import (
    GenerateEmailRequestSerializer,
    GeneratedEmailCreateUpdateSerializer,
    GeneratedEmailSerializer,
)
from research_ai.services.email_generator_service import generate_expert_email
from user.permissions import IsModerator

logger = logging.getLogger(__name__)

VALID_TEMPLATES = {
    "collaboration",
    "consultation",
    "conference",
    "peer-review",
    "publication",
    "rfp-outreach",
    "custom",
}


def _normalize_template(template: str) -> tuple[str, str | None]:
    """Return (template_key, custom_use_case or None). Supports 'custom: use case'."""
    template = (template or "").strip()
    if template.startswith("custom:"):
        return "custom", template[7:].strip() or None
    if template in VALID_TEMPLATES:
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

        try:
            subject, body = generate_expert_email(
                expert_name=expert_name,
                expert_title=data.get("expert_title") or "",
                expert_affiliation=data.get("expert_affiliation") or "",
                expertise=data.get("expertise") or "",
                notes=data.get("notes") or "",
                template=template_key,
                custom_use_case=custom_use_case,
            )
        except RuntimeError as e:
            logger.exception("Email generation failed")
            return Response(
                {"detail": str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

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
            uuid_val = UUID(email_id)
        except ValueError:
            return None, Response(
                {"detail": "Invalid email ID."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            email = GeneratedEmail.objects.get(id=uuid_val, created_by=request.user)
            return email, None
        except GeneratedEmail.DoesNotExist:
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


