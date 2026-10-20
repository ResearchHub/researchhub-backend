"""API for the AI-written post offered when sharing a proposal or RFP."""

import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.services.social_share_service import (
    SHAREABLE_DOCUMENT_TYPES,
    SharePostGenerationError,
    SocialShareService,
)
from research_ai.throttles import SharePostGenerateThrottle
from researchhub_document.related_models.researchhub_post_model import (
    ResearchhubPost,
)

logger = logging.getLogger(__name__)


class SharePostView(APIView):
    """Generate the post text for sharing a proposal or RFP on social media.

    POST rather than GET: an uncached call spends on a model, so it should not
    be prefetched or replayed by intermediaries.
    """

    permission_classes = [AllowAny]
    throttle_classes = [SharePostGenerateThrottle]

    def post(self, request, post_id: int):
        post = get_object_or_404(
            ResearchhubPost.objects.visible_to(request.user).filter(
                document_type__in=SHAREABLE_DOCUMENT_TYPES,
                unified_document__is_removed=False,
            ),
            pk=post_id,
        )
        try:
            text = SocialShareService().share_post_text(post)
        except SharePostGenerationError:
            logger.warning(
                "Share post generation failed for post %s", post.id, exc_info=True
            )
            return Response(
                {"detail": "Could not generate a post right now."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"text": text})
