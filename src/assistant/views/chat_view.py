import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from assistant.serializers import ChatRequestSerializer, ChatResponseSerializer
from assistant.services.bedrock_chat_service import BedrockChatService
from assistant.services.session_service import SessionService

logger = logging.getLogger(__name__)


class ChatView(APIView):
    """
    API endpoint for conversational AI chat interactions.

    POST /api/assistant/chat/

    Requires an existing session (created via POST /api/assistant/session/).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data
        session_id = validated_data["session_id"]
        message = validated_data["message"]
        structured_input = validated_data.get("structured_input")
        is_resume = validated_data.get("is_resume", False)

        # Look up session — must already exist
        session = SessionService.get_session(session_id, request.user)
        if not session:
            return Response(
                {"error": "Session not found or access denied"},
                status=status.HTTP_404_NOT_FOUND,
            )

        chat_service = BedrockChatService()

        # Handle resume: return progress summary without adding to history
        if is_resume:
            resume_response = chat_service.get_resume_message(session)
            response_data = {
                "session_id": session.id,
                "note_id": session.note_id,
                **resume_response,
            }
            return self._build_response(response_data, status.HTTP_200_OK)

        # First message in a new session — prepend the initial greeting
        if not session.conversation_history:
            initial_response = chat_service.get_initial_message(session.role)
            session.add_message("assistant", initial_response["message"])
            session.save()

        # Handle structured_input for note_id — store on session model directly
        if structured_input and structured_input.get("field") == "note_id":
            note_value = structured_input.get("value")
            if note_value is not None:
                session.note_id = int(note_value)
                session.save()

        # Process the message
        chat_response = chat_service.process_message(
            session=session,
            user_message=message,
            structured_input=structured_input,
        )

        response_data = {
            "session_id": session.id,
            "note_id": session.note_id,
            **chat_response,
        }

        return self._build_response(response_data, status.HTTP_200_OK)

    def _build_response(self, data, http_status):
        """Build and return a Response, logging serialization issues."""
        response_serializer = ChatResponseSerializer(data=data)
        if response_serializer.is_valid():
            return Response(response_serializer.data, status=http_status)
        else:
            logger.warning(
                f"Response serialization warning: {response_serializer.errors}"
            )
            return Response(data, status=http_status)
