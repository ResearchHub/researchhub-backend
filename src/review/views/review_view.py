from django.contrib.contenttypes.models import ContentType
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from discussion.models import Thread
from discussion.reaction_views import ReactionViewActionMixin
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    FILTER_PEER_REVIEWED,
)
from researchhub_document.related_models.constants.filters import DISCUSSED, HOT
from researchhub_document.utils import get_doc_type_key, reset_unified_document_cache
from review.models.review_model import Review
from review.permissions import AllowedToUpdateReview
from review.serializers import ReviewSerializer
from utils.sentry import log_error
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

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)

        try:
            thread = Thread.objects.get(review_id=response.data["id"])
            doc = thread.unified_document
            doc_type = get_doc_type_key(doc)
            hubs = list(doc.hubs.all().values_list("id", flat=True))

            reset_unified_document_cache(
                hub_ids=hubs,
                document_type=[doc_type, "all"],
                filters=[DISCUSSED, HOT],
            )
        except Exception as e:
            log_error(e)

        return response
