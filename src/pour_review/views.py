from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from pour_review.serializers import PuzzleSerializer, ResultSerializer
from pour_review.services.puzzle_service import PuzzleService


class PuzzleViewSet(viewsets.GenericViewSet):
    serializer_class = PuzzleSerializer
    permission_classes = [AllowAny]

    @action(detail=False, methods=["get"])
    def today(self, request: Request) -> Response:
        """Return today's puzzle with the signed-in user's progress."""
        puzzle = PuzzleService().get_todays_puzzle()
        return Response(self.get_serializer(puzzle).data)


class ResultViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = ResultSerializer
