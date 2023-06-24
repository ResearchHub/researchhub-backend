from django.contrib.contenttypes.models import ContentType
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from discussion.reaction_views import ReactionViewActionMixin
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    FILTER_PEER_REVIEWED,
)
from review.models.review_model import Review
from review.permissions import AllowedToUpdateReview
from review.serializers import ReviewSerializer
from utils.throttles import THROTTLE_CLASSES


class ReviewViewSet(viewsets.ModelViewSet, ReactionViewActionMixin):
    serializer_class = ReviewSerializer
    throttle_classes = THROTTLE_CLASSES

    permission_classes = [
        IsAuthenticatedOrReadOnly,
        AllowedToUpdateReview,
    ]
    filter_backends = (OrderingFilter,)
    order_fields = "__all__"
    queryset = Review.objects.all()
    ordering = ("-created_date",)
    ALLOWED_CONTENT_TYPES = [
        "rhcommentmodel",
    ]

    def create(self, request, *args, **kwargs):
        unified_document = ResearchhubUnifiedDocument.objects.get(id=args[0])
        request.data["created_by"] = request.user.id
        request.data["unified_document"] = unified_document.id

        if request.data.get("content_type") not in self.ALLOWED_CONTENT_TYPES:
            return Response({"detail": "Invalid content type"}, status=400)

        request.data["content_type"] = ContentType.objects.get(
            model=request.data.get("content_type", None)
        ).id

        response = super().create(request, *args, **kwargs)
        unified_document.update_filter(FILTER_PEER_REVIEWED)

        return response
