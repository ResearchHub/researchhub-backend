from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.permissions import (
    IsAuthenticatedOrReadOnly,
)
from rest_framework.decorators import action
from discussion.reaction_views import ReactionViewActionMixin
from review.models.review_model import Review
from utils.sentry import log_error
from discussion.serializers import ThreadSerializer
from review.permissions import (
    AllowedToCreateReview,
    AllowedToUpdateReview,
)
from utils import sentry
from review.serializers import ReviewSerializer
from utils.throttles import THROTTLE_CLASSES
from rest_framework.filters import OrderingFilter
from researchhub_document.models import (
    ResearchhubUnifiedDocument,
)
from researchhub_document.related_models.constants.filters import (
    DISCUSSED,
    TRENDING,
)

class ReviewViewSet(viewsets.ModelViewSet, ReactionViewActionMixin):
    serializer_class = ReviewSerializer
    throttle_classes = THROTTLE_CLASSES

    permission_classes = [
        IsAuthenticatedOrReadOnly
        & AllowedToCreateReview
        & AllowedToUpdateReview
    ]
    filter_backends = (OrderingFilter,)
    order_fields = '__all__'
    queryset = Review.objects.all()
    ordering = ('-created_date',)

    def create(self, request, *args, **kwargs):
        print(args[0])
        print(args)
        unified_document = ResearchhubUnifiedDocument.objects.get(id=args[0])
        print('unified_document', unified_document)
        request.data['created_by'] = request.user.id
        request.data['unified_document'] = unified_document.id

        response = super().create(request, *args, **kwargs)
        return response