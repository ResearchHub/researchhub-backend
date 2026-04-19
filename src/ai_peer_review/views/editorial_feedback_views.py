import logging

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ai_peer_review.models import EditorialFeedback
from ai_peer_review.permissions import AIPeerReviewPermission
from ai_peer_review.serializers import (
    EditorialFeedbackSerializer,
    EditorialFeedbackUpsertSerializer,
    replace_editorial_feedback_categories,
)
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.permissions import IsModerator, UserIsEditor

logger = logging.getLogger(__name__)

_EDITOR_PERMS = [IsAuthenticated, AIPeerReviewPermission, UserIsEditor | IsModerator]


class EditorialFeedbackUpsertView(APIView):
    """
    POST/PUT/PATCH /api/ai_peer_review/editorial-feedback/<unified_document_id>/.
    """

    permission_classes = _EDITOR_PERMS

    def put(self, request, unified_document_id):
        return self._upsert(request, unified_document_id, partial=False)

    def patch(self, request, unified_document_id):
        return self._upsert(request, unified_document_id, partial=True)

    def post(self, request, unified_document_id):
        return self._upsert(request, unified_document_id, partial=True)

    def _upsert(self, request, unified_document_id, partial):
        try:
            ud = ResearchhubUnifiedDocument.objects.get(pk=unified_document_id)
        except ResearchhubUnifiedDocument.DoesNotExist:
            return Response(
                {"detail": "Unified document not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if ud.document_type != PREREGISTRATION:
            return Response(
                {"detail": "Document must be a preregistration (proposal)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            existing = ud.ai_peer_review_editorial_feedback
        except ObjectDoesNotExist:
            existing = None

        if existing is None:
            ser = EditorialFeedbackUpsertSerializer(
                data=request.data,
                partial=False,
                context={"is_create": True},
            )
        else:
            ser = EditorialFeedbackUpsertSerializer(
                data=request.data,
                partial=partial,
                context={"is_create": False},
            )
        ser.is_valid(raise_exception=True)
        validated = ser.validated_data

        if existing is None:
            categories = validated["categories"]
            fb = EditorialFeedback.objects.create(
                unified_document=ud,
                created_by=request.user,
                updated_by=request.user,
                expert_insights=validated.get("expert_insights", ""),
            )
            replace_editorial_feedback_categories(fb, categories)
            return Response(
                EditorialFeedbackSerializer(fb).data,
                status=status.HTTP_201_CREATED,
            )
        if "expert_insights" in validated:
            existing.expert_insights = validated["expert_insights"]
        if "categories" in validated:
            replace_editorial_feedback_categories(existing, validated["categories"])
        existing.updated_by = request.user
        existing.save()
        return Response(EditorialFeedbackSerializer(existing).data)
