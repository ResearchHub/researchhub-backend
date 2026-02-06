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
        """
        Process a chat message and return the assistant's response.

        Request body:
        {
            "session_id": "uuid (optional)",
            "role": "researcher | funder (required for new sessions)",
            "message": "user's text message",
            "structured_input": {
                "field": "author_ids",
                "value": [142, 387]
            }
        }

        Response:
        {
            "session_id": "uuid",
            "message": "Bot's response",
            "follow_up": "Optional additional content",
            "input_type": "author_lookup | topic_select | ...",
            "quick_replies": [...],
            "field_updates": {...},
            "complete": false,
            "payload": null
        }
        """
        serializer = ChatRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data
        session_id = validated_data.get("session_id")
        role = validated_data.get("role")
        message = validated_data["message"]
        structured_input = validated_data.get("structured_input")

        try:
            # Get or create session
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

        # If this is a new session, return the initial greeting
        if created:
            chat_service = BedrockChatService()
            initial_response = chat_service.get_initial_message(session.role)

            # Add the initial message to conversation history
            session.add_message("assistant", initial_response["message"])
            session.save()

            response_data = {
                "session_id": session.id,
                **initial_response,
            }

            # Now process the user's first message
            chat_response = chat_service.process_message(
                session=session,
                user_message=message,
                structured_input=structured_input,
            )

            response_data = {
                "session_id": session.id,
                **chat_response,
            }

            response_serializer = ChatResponseSerializer(data=response_data)
            if response_serializer.is_valid():
                return Response(
                    response_serializer.data, status=status.HTTP_201_CREATED
                )
            else:
                logger.error(
                    f"Response serialization error: {response_serializer.errors}"
                )
                return Response(response_data, status=status.HTTP_201_CREATED)

        # Process message for existing session
        chat_service = BedrockChatService()
        chat_response = chat_service.process_message(
            session=session,
            user_message=message,
            structured_input=structured_input,
        )

        response_data = {
            "session_id": session.id,
            **chat_response,
        }

        response_serializer = ChatResponseSerializer(data=response_data)
        if response_serializer.is_valid():
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        else:
            # Log serialization issues but still return the response
            logger.warning(
                f"Response serialization warning: {response_serializer.errors}"
            )
            return Response(response_data, status=status.HTTP_200_OK)
