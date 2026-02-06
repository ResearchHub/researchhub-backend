import json
import logging
import re
from typing import Any, Optional

from django.conf import settings

from assistant.services.prompts import get_system_prompt
from utils import sentry
from utils.aws import create_client

logger = logging.getLogger(__name__)

# Use Claude Sonnet 4.5 for conversational AI (better reasoning than Haiku)
BEDROCK_CHAT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


class BedrockChatService:
    """
    Service for handling conversational AI interactions using AWS Bedrock.

    Uses Claude Sonnet via the Converse API for multi-turn conversations
    that help users create proposals or funding opportunities.
    """

    def __init__(self):
        self.enabled = getattr(settings, "ASSISTANT_ENABLED", False)
        if self.enabled:
            self.bedrock_client = create_client("bedrock-runtime")
        else:
            self.bedrock_client = None
        self.model_id = getattr(
            settings, "ASSISTANT_BEDROCK_MODEL_ID", BEDROCK_CHAT_MODEL_ID
        )

    def process_message(
        self,
        session,
        user_message: str,
        structured_input: Optional[dict] = None,
    ) -> dict:
        """
        Process a user message and return the assistant's response.

        Args:
            session: AssistantSession instance
            user_message: The user's text message
            structured_input: Optional structured data from UI components

        Returns:
            dict with message, follow_up, input_type, quick_replies,
            field_updates, complete, and payload
        """
        if not self.enabled or not self.bedrock_client:
            logger.warning("Assistant is disabled, returning fallback response")
            return self._fallback_response()

        try:
            # Handle structured input — directly update field state for confirmed values
            if structured_input:
                field = structured_input.get("field")
                value = structured_input.get("value")
                if field and value is not None:
                    session.update_field(field, "complete", value)

            # Build the full message including any structured input context
            full_message = self._build_user_message(user_message, structured_input)

            # Add user message to conversation history
            session.add_message("user", full_message)

            # Build messages for Bedrock
            messages = self._build_messages(session.conversation_history)

            # Get system prompt based on role
            system_prompt = get_system_prompt(session.role, session.field_state)

            # Call Bedrock
            response_text = self._call_bedrock(system_prompt, messages)

            if response_text is None:
                session.conversation_history.pop()  # Remove failed user message
                return self._error_response()

            # Parse structured output from response
            parsed = self._parse_structured_output(response_text)

            # Extract the conversational message (without structured tags)
            clean_message = self._extract_clean_message(response_text)

            # Add assistant message to history
            session.add_message("assistant", clean_message)

            # Update field state if there are updates
            if parsed.get("field_updates"):
                for field_name, field_data in parsed["field_updates"].items():
                    session.update_field(
                        field_name,
                        field_data.get("status", "draft"),
                        field_data.get("value"),
                    )

            # Check completion
            is_complete = session.check_completion()
            session.is_complete = is_complete

            # Build payload if complete
            payload = None
            if is_complete and parsed.get("input_type") == "final_review":
                payload = self._build_payload(session)
                session.payload = payload

            session.save()

            return {
                "message": clean_message,
                "follow_up": parsed.get("follow_up"),
                "input_type": parsed.get("input_type"),
                "editor_field": parsed.get("editor_field"),
                "quick_replies": parsed.get("quick_replies"),
                "field_updates": parsed.get("field_updates"),
                "complete": is_complete,
                "payload": payload,
            }

        except Exception as e:
            sentry.log_error(e, message="BedrockChatService.process_message failed")
            logger.exception("Error processing message")
            # Remove the user message if we added it
            if (
                session.conversation_history
                and session.conversation_history[-1].get("role") == "user"
            ):
                session.conversation_history.pop()
            return self._error_response()

    def _build_user_message(
        self, user_message: str, structured_input: Optional[dict]
    ) -> str:
        """Build the full user message including any structured input context."""
        if not structured_input:
            return user_message

        # Append structured input information to the message
        field = structured_input.get("field", "")
        value = structured_input.get("value", "")

        if field == "author_ids" and isinstance(value, list):
            return f"{user_message}\n\n[Selected authors with IDs: {value}]"
        elif field == "topic_ids" and isinstance(value, list):
            return f"{user_message}\n\n[Selected topics/hubs with IDs: {value}]"
        elif field == "nonprofit_id":
            return f"{user_message}\n\n[Selected nonprofit with ID: {value}]"
        elif field == "description":
            # Rich editor content — value is a Tiptap JSON string or raw HTML
            return f"{user_message}\n\n[User edited the description in the rich editor. Content confirmed.]"

        return user_message

    def _build_messages(self, conversation_history: list) -> list:
        """
        Build messages array for Bedrock Converse API.

        Args:
            conversation_history: List of {"role": "user"|"assistant", "content": str}

        Returns:
            List of message dicts formatted for Bedrock
        """
        messages = []
        for msg in conversation_history:
            messages.append(
                {
                    "role": msg["role"],
                    "content": [{"text": msg["content"]}],
                }
            )
        return messages

    def _call_bedrock(self, system_prompt: str, messages: list) -> Optional[str]:
        """
        Call Bedrock Converse API.

        Args:
            system_prompt: The system prompt for the assistant
            messages: List of conversation messages

        Returns:
            The assistant's response text, or None on failure
        """
        try:
            logger.info(f"Calling Bedrock Converse API with {len(messages)} messages")

            response = self.bedrock_client.converse(
                modelId=self.model_id,
                system=[{"text": system_prompt}],
                messages=messages,
                inferenceConfig={
                    "maxTokens": 4096,
                    "temperature": 0.7,
                },
            )

            if "output" not in response or not response["output"].get("message"):
                logger.error("Invalid response from Bedrock: missing output message")
                return None

            message = response["output"]["message"]
            content = message.get("content", [])

            # Extract text from content blocks
            response_text = ""
            for block in content:
                if "text" in block:
                    response_text += block["text"]

            logger.info(f"Received response from Bedrock ({len(response_text)} chars)")
            return response_text

        except Exception as e:
            sentry.log_error(e, message="Bedrock API call failed")
            logger.exception("Bedrock API error")
            return None

    def _parse_structured_output(self, response_text: str) -> dict:
        """
        Parse structured output from the assistant's response.

        Extracts JSON from <structured> tags.

        Args:
            response_text: The full response text from the assistant

        Returns:
            dict with input_type, quick_replies, field_updates, follow_up
        """
        result = {
            "input_type": None,
            "editor_field": None,
            "quick_replies": None,
            "field_updates": None,
            "follow_up": None,
        }

        # Look for <structured>...</structured> tags
        pattern = r"<structured>\s*(.*?)\s*</structured>"
        match = re.search(pattern, response_text, re.DOTALL)

        if not match:
            logger.debug("No structured output found in response")
            return result

        try:
            json_str = match.group(1).strip()
            parsed = json.loads(json_str)

            result["input_type"] = parsed.get("input_type")
            result["editor_field"] = parsed.get("editor_field")
            result["quick_replies"] = parsed.get("quick_replies")
            result["field_updates"] = parsed.get("field_updates")
            result["follow_up"] = parsed.get("follow_up")

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse structured output JSON: {e}")

        return result

    def _extract_clean_message(self, response_text: str) -> str:
        """
        Remove structured output tags from the response for display.

        Args:
            response_text: The full response text

        Returns:
            Clean message without <structured> tags
        """
        # Remove <structured>...</structured> blocks
        pattern = r"<structured>.*?</structured>"
        clean = re.sub(pattern, "", response_text, flags=re.DOTALL)
        return clean.strip()

    def _build_payload(self, session) -> dict:
        """
        Build the submission payload from collected fields.

        Args:
            session: AssistantSession with completed field_state

        Returns:
            dict payload matching the expected format for submission
        """
        fields = session.get_complete_fields()

        if session.role == "researcher":
            return {
                "title": fields.get("title", ""),
                "renderable_text": fields.get("description", ""),
                "full_src": fields.get("description", ""),  # Markdown source
                "document_type": "PREREGISTRATION",
                "hubs": fields.get("topic_ids", []),
                "authors": fields.get("author_ids", []),
                "fundraise_goal_amount": fields.get("funding_amount_rsc"),
                "fundraise_goal_currency": "USD",
            }
        else:  # funder
            return {
                "title": fields.get("title", ""),
                "description": fields.get("description", ""),
                "amount": fields.get("amount"),
                "currency": fields.get("currency", "USD"),
                "hubs": fields.get("topic_ids", []),
                "contact_ids": fields.get("contact_ids", []),
                "end_date": fields.get("deadline"),
            }

    def _fallback_response(self) -> dict:
        """Return a fallback response when the service is disabled."""
        return {
            "message": "The assistant is currently unavailable. Please try again later or use the standard form.",
            "follow_up": None,
            "input_type": None,
            "editor_field": None,
            "quick_replies": None,
            "field_updates": None,
            "complete": False,
            "payload": None,
        }

    def _error_response(self) -> dict:
        """Return an error response."""
        return {
            "message": "Sorry, I encountered an issue processing your message. Please try again.",
            "follow_up": None,
            "input_type": None,
            "editor_field": None,
            "quick_replies": [
                {"label": "Try again", "value": "Let's continue where we left off."},
            ],
            "field_updates": None,
            "complete": False,
            "payload": None,
        }

    def get_initial_message(self, role: str) -> dict:
        """
        Get the initial greeting message for a new session.

        Args:
            role: "researcher" or "funder"

        Returns:
            dict with the initial message and quick replies
        """
        if role == "researcher":
            message = (
                "Hi! I'm here to help you create a compelling research proposal. "
                "I can help you brainstorm ideas, draft your title and description, "
                "and guide you through the process.\n\n"
                "What would you like to do?"
            )
            quick_replies = [
                {
                    "label": "I have an idea",
                    "value": "I have a research idea I'd like to develop into a proposal.",
                },
                {
                    "label": "Help me brainstorm",
                    "value": "I'm not sure what to propose. Can you help me brainstorm ideas?",
                },
                {
                    "label": "I have a draft ready",
                    "value": "I already have a draft proposal I'd like to refine.",
                },
            ]
        else:  # funder
            message = (
                "Hi! I'm here to help you create an effective funding opportunity. "
                "I can help you define what kind of research you want to fund, "
                "set up your requirements, and guide you through the process.\n\n"
                "What would you like to do?"
            )
            quick_replies = [
                {
                    "label": "I know what I want to fund",
                    "value": "I have a specific research area I want to fund.",
                },
                {
                    "label": "Help me define scope",
                    "value": "I want to fund research but need help defining the scope.",
                },
                {
                    "label": "Review my draft",
                    "value": "I have a draft funding opportunity I'd like to refine.",
                },
            ]

        return {
            "message": message,
            "follow_up": None,
            "input_type": None,
            "editor_field": None,
            "quick_replies": quick_replies,
            "field_updates": None,
            "complete": False,
            "payload": None,
        }
