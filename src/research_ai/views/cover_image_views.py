"""API for AI-generated proposal and RFP cover images.

1. ``POST cover-images/`` with the banner's text, and optionally the
   ``note_id`` of the draft whose cover logo (an image the chat agent recorded
   from the note's chat) to place in it, starts generating (``PENDING``).
2. Poll ``GET cover-images/<id>/`` until ``COMPLETED`` (with ``image``, a
   ``key`` and ``url``) or ``FAILED`` (with ``error``).
3. Send the image's ``key`` as the post's ``image``, like an uploaded cover.

Requests are private to their creator: another user's id is a 404.
"""

from django.http import Http404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.permissions import ResearchAIBudgetPermission
from research_ai.serializers import CoverImageGenerationCreateSerializer
from research_ai.services.cover_image_service import (
    CoverImageGenerationEnqueueError,
    CoverImageNoteError,
    CoverImageService,
)
from research_ai.services.usage_budget import UsageLimitExceededError
from research_ai.throttles import CoverImageGenerationThrottle


class CoverImageGenerationCreateView(APIView):
    """Start generating a cover image."""

    permission_classes = [IsAuthenticated, ResearchAIBudgetPermission]
    throttle_classes = [CoverImageGenerationThrottle]

    def post(self, request):
        serializer = CoverImageGenerationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = CoverImageService()
        try:
            generation = service.start(user=request.user, **serializer.validated_data)
        except CoverImageNoteError as error:
            return Response(
                {"detail": str(error), "code": "note_not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except UsageLimitExceededError as error:
            return Response(
                {
                    "detail": "Daily AI usage limit reached.",
                    "code": error.code,
                    **error.status.as_dict(),
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except CoverImageGenerationEnqueueError:
            return Response(
                {
                    "detail": "Could not start cover image generation.",
                    "code": "cover_image_generation_enqueue_failed",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(service.public(generation), status=status.HTTP_201_CREATED)


class CoverImageGenerationDetailView(APIView):
    """Read a generation request's state and, once done, its image."""

    permission_classes = [IsAuthenticated, ResearchAIBudgetPermission]

    def get(self, request, generation_id):
        service = CoverImageService()
        generation = service.get_for_user(request.user, generation_id)
        if generation is None:
            raise Http404
        return Response(service.public(generation))
