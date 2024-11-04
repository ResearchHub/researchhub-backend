import logging

from django.db import IntegrityError
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from review.models.peer_review_model import PeerReview
from review.serializers.peer_review_serializer import PeerReviewSerializer

logger = logging.getLogger(__name__)


class PeerReviewViewSet(viewsets.ModelViewSet):
    """
    Views for peer reviews on papers.
    """

    permission_classes = [
        IsAuthenticatedOrReadOnly,
    ]
    queryset = PeerReview.objects.all()
    serializer_class = PeerReviewSerializer

    def initial(self, request, *args, **kwargs):
        return super().initial(request, *args, **kwargs)

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
        except IntegrityError as e:
            logger.warning(
                "Failed to insert peer review for paper %s: %s",
                paper,
                e,
            )
            return Response(
                {"message": "Invalid request"},
                status=status.HTTP_409_CONFLICT,
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
