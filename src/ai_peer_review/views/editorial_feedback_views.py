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
            ser = EditorialFeedbackUpsertSerializer(data=request.data, partial=False)
        else:
            ser = EditorialFeedbackUpsertSerializer(
                existing,
                data=request.data,
                partial=partial,
            )
        ser.is_valid(raise_exception=True)

        if existing is None:
            fb = EditorialFeedback.objects.create(
                unified_document=ud,
                created_by=request.user,
                updated_by=request.user,
                **ser.validated_data,
            )
            return Response(
                EditorialFeedbackSerializer(fb).data,
                status=status.HTTP_201_CREATED,
            )
        for attr, value in ser.validated_data.items():
            setattr(existing, attr, value)
        existing.updated_by = request.user
        existing.save()
        return Response(EditorialFeedbackSerializer(existing).data)
