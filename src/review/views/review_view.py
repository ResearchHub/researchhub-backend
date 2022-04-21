from httplib2 import Response
from rest_framework import status, viewsets
from rest_framework.permissions import (
    IsAuthenticatedOrReadOnly,
)
from review.permissions import (
    CreateReview,
    UpdateReview,
)
from review.serializers import ReviewSerializer
from utils.throttles import THROTTLE_CLASSES
from rest_framework.filters import OrderingFilter
from researchhub_document.models import (
    ResearchhubUnifiedDocument,
)
from discussion.services import create_thread
from review.services import create_review

class ReviewViewSet(viewsets.ModelViewSet):
    serializer_class = ReviewSerializer
    throttle_classes = THROTTLE_CLASSES

    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreateReview
        & UpdateReview
    ]
    filter_backends = (OrderingFilter,)
    order_fields = '__all__'
    ordering = ('-created_date',)

    def create(self, request, pk, **kwargs):
        unified_document = ResearchhubUnifiedDocument.objects.get(id=pk)
        thread = create_thread(
            data=request.data['discussion'],
            user=request.user,
            for_model=unified_document.get_document().__class__.__name__,
            for_model_id=unified_document.get_document().id,
            context={'request': request}
        )

        review = create_review(
            data=request.data['review'],
            unified_document=unified_document,
            context={'request': request}
        )

        thread.review = review
        thread.save()

        return Response('a')