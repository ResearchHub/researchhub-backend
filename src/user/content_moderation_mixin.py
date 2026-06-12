from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from user.permissions import IsModerator
from user.services.content_moderation_service import ContentModerationService


class ContentModerationActionsMixin:
    """Moderator approve/decline actions backed by ContentModerationService.

    Set ``moderation_model`` on the viewset to the model the actions operate on.
    """

    moderation_model = None

    @action(detail=True, methods=["post"], permission_classes=[IsModerator])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        content = get_object_or_404(self.moderation_model, pk=pk)
        try:
            ContentModerationService().approve_content(content, request.user)
        except ValueError as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(self._moderation_result(content))

    @action(detail=True, methods=["post"], permission_classes=[IsModerator])
    def decline(self, request: Request, pk: str | None = None) -> Response:
        content = get_object_or_404(self.moderation_model, pk=pk)
        try:
            ContentModerationService().decline_content(
                content,
                request.user,
                request.data.get("reason", ""),
                request.data.get("reason_choice", ""),
            )
        except ValueError as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(self._moderation_result(content))

    def _moderation_result(self, content):
        unified_document = content.unified_document
        return {
            "id": content.id,
            "status": unified_document.status,
            "reviewed_by": unified_document.reviewed_by_id,
            "reviewed_date": unified_document.reviewed_date,
        }
