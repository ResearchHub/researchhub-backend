from django.db import IntegrityError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ai_peer_review.models import EditorialFeedback
from ai_peer_review.permissions import AIPeerReviewPermission
from ai_peer_review.serializers import (
    EditorialFeedbackCreateSerializer,
    EditorialFeedbackSerializer,
    EditorialFeedbackUpdateSerializer,
)
from user.permissions import IsModerator, UserIsEditor

_EDITOR_PERMS = [IsAuthenticated, AIPeerReviewPermission, UserIsEditor | IsModerator]


class EditorialFeedbackCreateView(APIView):
    permission_classes = _EDITOR_PERMS

    def post(self, request):
        ser = EditorialFeedbackCreateSerializer(
            data=request.data, context={"request": request}
        )
        ser.is_valid(raise_exception=True)
        try:
            obj = ser.save()
        except IntegrityError:
            return Response(
                {"detail": "Feedback already exists for this review and user."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            EditorialFeedbackSerializer(obj).data,
            status=status.HTTP_201_CREATED,
        )


class EditorialFeedbackUpdateView(APIView):
    permission_classes = _EDITOR_PERMS

    def patch(self, request, feedback_id):
        try:
            fb = EditorialFeedback.objects.get(pk=feedback_id)
        except EditorialFeedback.DoesNotExist:
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
            )
        if fb.user_id != request.user.id and not getattr(
            request.user, "moderator", False
        ):
            return Response(
                {"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN
            )
        ser = EditorialFeedbackUpdateSerializer(
            fb, data=request.data, partial=True
        )
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(EditorialFeedbackSerializer(fb).data)
