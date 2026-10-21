"""API for the AI-written post offered when sharing a proposal or RFP."""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.services.social_share_service import (
    FAILED,
    READY,
    SHAREABLE_DOCUMENT_TYPES,
    SocialShareService,
)
from research_ai.throttles import SharePostGenerateThrottle
from researchhub_document.related_models.researchhub_post_model import (
    ResearchhubPost,
)


class SharePostView(APIView):
    """The post text for sharing a proposal or RFP on social media.

    A cached post comes back at once. Otherwise a worker task writes it and the
    response is 202; the client repeats the request until the post is ready.
    POST rather than GET: a miss queues a paid model call, so the request
    should not be prefetched or replayed by intermediaries.
    """

    permission_classes = [AllowAny]

    def post(self, request, post_id: int):
        post = get_object_or_404(
            ResearchhubPost.objects.visible_to(request.user).filter(
                document_type__in=SHAREABLE_DOCUMENT_TYPES,
                unified_document__is_removed=False,
            ),
            pk=post_id,
        )
        share_post = SocialShareService().request_post(
            post, on_enqueue=lambda: self._throttle_generation(request)
        )
        if share_post.status == READY:
            return Response({"status": READY, "text": share_post.text})
        if share_post.status == FAILED:
            return Response(
                {"status": FAILED, "detail": "Could not generate a post right now."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"status": share_post.status}, status=status.HTTP_202_ACCEPTED)

    def _throttle_generation(self, request):
        # Only queueing a generation counts: polls for its result do not.
        throttle = SharePostGenerateThrottle()
        if not throttle.allow_request(request, self):
            self.throttled(request, throttle.wait())
