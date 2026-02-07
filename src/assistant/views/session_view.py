import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from assistant.serializers import (
    CreateSessionRequestSerializer,
    CreateSessionResponseSerializer,
    SessionDetailSerializer,
    SessionListSerializer,
)
from assistant.services.session_service import SessionService

logger = logging.getLogger(__name__)


class SessionCreateView(APIView):
    """
    POST /api/assistant/session/

    Create a new assistant session.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateSessionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        role = serializer.validated_data["role"]

        try:
            session, _ = SessionService.get_or_create_session(
                user=request.user,
                role=role,
            )
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = CreateSessionResponseSerializer(
            data={"session_id": session.id}
        )
        response_serializer.is_valid()
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class SessionDetailView(APIView):
    """
    GET /api/assistant/session/<uuid>/

    Retrieve session state (no conversation history).
    Only the session creator can access it.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        session = SessionService.get_session(session_id, request.user)
        if not session:
            return Response(
                {"error": "Session not found or access denied"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = SessionDetailSerializer(session)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SessionListView(APIView):
    """
    GET /api/assistant/session/list/

    List the authenticated user's recent sessions.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = request.query_params.get("limit", 10)
        try:
            limit = min(int(limit), 50)
        except (ValueError, TypeError):
            limit = 10

        sessions = SessionService.get_user_sessions(request.user, limit=limit)
        serializer = SessionListSerializer(sessions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
