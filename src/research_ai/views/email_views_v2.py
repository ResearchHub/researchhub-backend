import logging

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.models import ExpertSearch, GeneratedEmail
from research_ai.permissions import ResearchAIPermission
from research_ai.serializers import (
    BulkGenerateEmailRequestSerializer,
    GeneratedEmailSerializer,
    GenerateEmailRequestSerializer,
)
from research_ai.services.email_generator_service import generate_expert_email
from research_ai.services.email_template_variables import format_expert_name_from_raw
from research_ai.services.expert_email_resolution_v2 import (
    resolve_expert_from_search_v2,
)
from research_ai.tasks import process_bulk_generate_emails_task
from research_ai.views.email_views import (
    _resolve_generate_llm_params,
    _stored_template_for_bulk,
)
from user.permissions import IsModerator, UserIsEditor

logger = logging.getLogger(__name__)


class GenerateEmailViewV2(APIView):
    """
    POST ``/expert-finder/v2/generate-email/`` — always persists a draft ``GeneratedEmail``
    (no ``save=false`` / ``action=generate`` preview-only mode).
    """

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

        resolved = resolve_expert_from_search_v2(expert_search, data["expert_email"])
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

        stored_template = None if template_key is None else template_key
        email_record = GeneratedEmail.objects.create(
            created_by=request.user,
            expert_search=expert_search,
            expert_name=format_expert_name_from_raw(resolved.get("name") or ""),
            expert_title=resolved.get("title") or "",
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


class BulkGenerateEmailViewV2(APIView):
    """
    POST ``/expert-finder/v2/generate-emails-bulk/``
    """

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
                    resolved = resolve_expert_from_search_v2(
                        expert_search, item["expert_email"]
                    )
                    if not resolved:
                        raise ValueError(
                            f"Expert not found in search results: {item['expert_email']}."
                        )
                    email_record = GeneratedEmail.objects.create(
                        created_by=request.user,
                        expert_search=expert_search,
                        expert_name=format_expert_name_from_raw(
                            resolved.get("name") or ""
                        ),
                        expert_title=resolved.get("title") or "",
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
