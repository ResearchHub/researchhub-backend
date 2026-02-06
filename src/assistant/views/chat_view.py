import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from assistant.models import AssistantSession
from assistant.serializers import ChatRequestSerializer, ChatResponseSerializer
from assistant.services.bedrock_chat_service import BedrockChatService
from assistant.services.session_service import SessionService

logger = logging.getLogger(__name__)


class ChatView(APIView):
    """
    API endpoint for conversational AI chat interactions.

    POST /api/assistant/chat/

    Handles multi-turn conversations with the AI assistant to help users
    create research proposals or funding opportunities.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data
        session_id = validated_data.get("session_id")
        role = validated_data.get("role")
        message = validated_data["message"]
        structured_input = validated_data.get("structured_input")
        is_resume = validated_data.get("is_resume", False)

        try:
            session, created = SessionService.get_or_create_session(
                user=request.user,
                session_id=session_id,
                role=role,
            )
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except AssistantSession.DoesNotExist:
            return Response(
                {"error": "Session not found or access denied"},
                status=status.HTTP_404_NOT_FOUND,
            )

        chat_service = BedrockChatService()

        # Handle resume: return progress summary without adding to history
        if is_resume and not created:
            resume_response = chat_service.get_resume_message(session)
            response_data = {
                "session_id": session.id,
                "note_id": session.note_id,
                **resume_response,
            }
            return self._build_response(response_data, status.HTTP_200_OK)

        # Handle structured_input for note_id — store on session model directly
        if structured_input and structured_input.get("field") == "note_id":
            note_value = structured_input.get("value")
            if note_value is not None:
                session.note_id = int(note_value)
                session.save()

        # New session: add initial greeting then process the first message
        if created:
            initial_response = chat_service.get_initial_message(session.role)
            session.add_message("assistant", initial_response["message"])
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

        http_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return self._build_response(response_data, http_status)

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
