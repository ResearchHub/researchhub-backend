from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.permissions import (
    IsAuthenticated
)
from peer_review.permissions import (
    IsAllowedToCreateDecision,
)
from utils.http import DELETE, POST, PATCH, PUT, GET
from peer_review.models import (
    PeerReviewDecision,
    PeerReview,
)
from peer_review.serializers import (
    PeerReviewDecisionSerializer,
    PeerReviewSerializer,
)
from rest_framework.response import Response


class PeerReviewViewSet(ModelViewSet):
    permission_classes = [
        IsAuthenticated,
    ]
    serializer_class = PeerReviewSerializer
    queryset = PeerReview.objects.all()

    def get_serializer_class(self):
        if self.action == 'create_decision':
            return PeerReviewDecisionSerializer
        else:
            return self.serializer_class

    @action(
        detail=True,
        methods=[POST],
        permission_classes=[IsAllowedToCreateDecision]
    )
    def create_decision(self, request, pk=None):
        review = self.get_object()
        request.data['unified_document'] = review.unified_document.id

        serializer = self.get_serializer(data=request.data)
        serializer.context['peer_review'] = review
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        return Response(serializer.data)
