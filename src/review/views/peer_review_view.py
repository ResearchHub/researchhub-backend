import logging

from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from review.models.peer_review_model import PeerReview
from review.serializers.peer_review_serializer import PeerReviewSerializer
from user.permissions import IsModerator

logger = logging.getLogger(__name__)


class PeerReviewViewSet(viewsets.ModelViewSet):
    """
    Views for peer reviews on papers.
    """

    queryset = PeerReview.objects.all()
    serializer_class = PeerReviewSerializer

    def get_permissions(self):
        if self.action == "list":
            return []
        else:
            return [IsModerator()]

    def get_queryset(self):
        paper_id = self.kwargs.get("paper_id")
        if not paper_id:
            return PeerReview.objects.none()

        return PeerReview.objects.filter(paper_id=paper_id)

    def create(self, request, *args, **kwargs):
        data = request.data
        paper = data.get("paper")

        try:
            return super().create(request, *args, **kwargs)
        except ValidationError as e:
            return Response(
                {"message": e.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(
                "Failed to create peer review for paper [%s]: %s",
                paper,
                e,
            )
            return Response(
                {"message": "An error occurred while creating the peer review"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def update(self, request, *args, **kwargs):
        data = request.data
        paper = data.get("paper")

        try:
            return super().update(request, *args, **kwargs)
        except ValidationError as e:
            return Response(
                {"message": e.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(
                "Failed to update peer review for paper [%s]: %s",
                paper,
                e,
            )
            return Response(
                {"message": "An error occurred while updating the peer review"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
