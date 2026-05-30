from django.shortcuts import get_object_or_404
from rest_framework.decorators import action
from rest_framework.response import Response

from user.permissions import IsModerator
from user.services.content_moderation_service import ContentModerationService


class ContentModerationActionsMixin:
    """Moderator approve/decline actions backed by ContentModerationService.

    Set ``moderation_model`` on the viewset to the model the actions operate on.
    """

    moderation_model = None

    @action(detail=True, methods=["post"], permission_classes=[IsModerator])
    def approve(self, request, pk=None):
        content = get_object_or_404(self.moderation_model, pk=pk)
        try:
            ContentModerationService().approve_content(content, request.user)
        except ValueError as e:
            return Response({"message": str(e)}, status=400)

        return Response(self.get_serializer(content).data)

    @action(detail=True, methods=["post"], permission_classes=[IsModerator])
    def decline(self, request, pk=None):
        content = get_object_or_404(self.moderation_model, pk=pk)
        try:
            ContentModerationService().decline_content(
                content,
                request.user,
                request.data.get("reason", ""),
                request.data.get("reason_choice", ""),
            )
        except ValueError as e:
            return Response({"message": str(e)}, status=400)

        return Response(self.get_serializer(content).data)
