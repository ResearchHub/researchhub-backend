from rest_framework import status, viewsets
from rest_framework.permissions import (
    IsAuthenticatedOrReadOnly,
    IsAuthenticated
)
from review.permissions import (
    CreateReview,
    UpdateReview,
)
from review.serializers import ReviewSerializer
from utils.throttles import THROTTLE_CLASSES
from rest_framework.filters import OrderingFilter


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

    def create(self, request, *args, **kwargs):
        print('kwargs', kwargs)
        print('args', args)