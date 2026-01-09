from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from review.serializers import ReviewAvailabilitySerializer
from review.services.review_service import get_review_availability


class ReviewAvailabilityView(APIView):
    """Returns the authenticated user's review availability status."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        availability = get_review_availability(request.user)
        serializer = ReviewAvailabilitySerializer(availability)
        return Response(serializer.data)

