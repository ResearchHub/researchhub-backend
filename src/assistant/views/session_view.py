import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from assistant.serializers import SessionDetailSerializer, SessionListSerializer
from assistant.services.session_service import SessionService

logger = logging.getLogger(__name__)


class SessionDetailView(APIView):
    """
    API endpoint for retrieving a single assistant session.

    GET /api/assistant/sessions/<uuid>/

    Returns the full session including conversation history and field state.
    Only the session creator can access their own sessions.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        """
        Retrieve a session by ID.

        Only returns sessions owned by the authenticated user.
        """
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
    API endpoint for listing a user's assistant sessions.

    GET /api/assistant/sessions/

    Returns recent sessions for the authenticated user.
    Only returns sessions belonging to the requesting user.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        List the authenticated user's sessions.

        Query params:
            limit (int): Max sessions to return (default 10, max 50)
        """
        limit = request.query_params.get("limit", 10)
        try:
            limit = min(int(limit), 50)
        except (ValueError, TypeError):
            limit = 10

        sessions = SessionService.get_user_sessions(request.user, limit=limit)
        serializer = SessionListSerializer(sessions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
