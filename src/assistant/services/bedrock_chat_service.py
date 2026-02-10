import json
import logging
import re
import time
from typing import Any, Optional

from django.conf import settings

from assistant.config import FieldStatus
from assistant.services.prompts import get_system_prompt
from utils import sentry
from utils.aws import create_client

logger = logging.getLogger(__name__)

# Use Claude Sonnet 4.5 for conversational AI (better reasoning than Haiku)
BEDROCK_CHAT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

# Module-level singleton for the Bedrock client (boto3 clients are thread-safe)
_bedrock_client = None


def _get_bedrock_client():
    """Get or create the singleton Bedrock client."""
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = create_client("bedrock-runtime")
        logger.info("Created Bedrock client (singleton)")
    return _bedrock_client


class BedrockChatService:
    """
    Service for handling conversational AI interactions using AWS Bedrock.

    Uses Claude Sonnet via the Converse API for multi-turn conversations
    that help users create proposals or funding opportunities.
    """

    def __init__(self):
        self.enabled = getattr(settings, "ASSISTANT_ENABLED", False)
        self.bedrock_client = _get_bedrock_client() if self.enabled else None
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
                    session.update_field(field, FieldStatus.COMPLETE, value)

            # Build the full message including any structured input context
            full_message = self._build_user_message(user_message, structured_input)

            # Add user message to conversation history
            session.add_message("user", full_message)

            # Build messages for Bedrock
            messages = self._build_messages(session.conversation_history)

            # Get system prompt based on role
            system_prompt = get_system_prompt(session.role, session.field_state)

            # Inject current document draft if the note has changed
            note_content = self._get_note_content_if_changed(session)
            if note_content is not None:
                system_prompt += (
                    "\n\n## CURRENT DOCUMENT DRAFT\n"
                    "The user's current document content is below. "
                    "Use this as the basis when they ask for changes. "
                    "When returning an updated document via rich_editor, "
                    "incorporate any edits the user made.\n\n"
                    f"{note_content}"
                )

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
                    raw_status = field_data.get("status", "ai_suggested")
                    # Normalize: the LLM may output "draft" — map to ai_suggested
                    if raw_status == "draft":
                        raw_status = FieldStatus.AI_SUGGESTED
                    session.update_field(
                        field_name,
                        raw_status,
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

    def _get_note_content_if_changed(self, session) -> Optional[str]:
        """
        Fetch the note's plain_text if the document has changed since
        the AI last saw it.

        Returns:
            The note's plain_text if changed, None otherwise.
            Also updates session.last_seen_note_content_id.
        """
        if not session.note_id:
            return None

        try:
            from note.related_models.note_model import Note

            note = Note.objects.select_related("latest_version").get(id=session.note_id)
        except Note.DoesNotExist:
            logger.warning(f"Note {session.note_id} not found for session {session.id}")
            return None

        latest_version = note.latest_version
        if not latest_version:
            return None

        # Check if the version has changed since we last sent it
        if session.last_seen_note_content_id == latest_version.id:
            return None

        # Version changed (or first time) — return content if available
        plain_text = latest_version.plain_text

        if not plain_text:
            return None

        # Only mark as seen if we actually have content to send
        session.last_seen_note_content_id = latest_version.id

        logger.info(
            f"Note content changed for session {session.id} "
            f"(note_content_id: {latest_version.id})"
        )
        return plain_text

    def _build_user_message(
        self, user_message: str, structured_input: Optional[dict]
    ) -> str:
        """Build the full user message including any structured input context."""
        if not structured_input:
            return user_message

        # Append structured input information to the message
        field = structured_input.get("field", "")
        value = structured_input.get("value", "")

        if field == "authors" and isinstance(value, list):
            return f"{user_message}\n\n[Selected authors with IDs: {value}]"
        elif field == "hubs" and isinstance(value, list):
            return f"{user_message}\n\n[Selected topics/hubs with IDs: {value}]"
        elif field == "nonprofit":
            return f"{user_message}\n\n[Selected nonprofit with ID: {value}]"
        elif field == "grant_contacts" and isinstance(value, list):
            return f"{user_message}\n\n[Selected contact persons with IDs: {value}]"

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
            # Log input sizes for debugging
            system_prompt_len = len(system_prompt)
            history_len = sum(
                len(block["text"])
                for msg in messages
                for block in msg.get("content", [])
                if "text" in block
            )
            logger.info(
                f"Calling Bedrock Converse API: "
                f"model={self.model_id}, "
                f"messages={len(messages)}, "
                f"system_prompt_chars={system_prompt_len}, "
                f"history_chars={history_len}"
            )

            start_time = time.time()

            response = self.bedrock_client.converse(
                modelId=self.model_id,
                system=[{"text": system_prompt}],
                messages=messages,
                inferenceConfig={
                    "maxTokens": 4096,
                    "temperature": 0.7,
                },
            )

            elapsed = time.time() - start_time

            # Log usage and performance metrics
            usage = response.get("usage", {})
            metrics = response.get("metrics", {})
            stop_reason = response.get("stopReason", "unknown")
            logger.info(
                f"Bedrock response: "
                f"elapsed={elapsed:.1f}s, "
                f"input_tokens={usage.get('inputTokens', '?')}, "
                f"output_tokens={usage.get('outputTokens', '?')}, "
                f"latency_ms={metrics.get('latencyMs', '?')}, "
                f"stop_reason={stop_reason}"
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

            logger.info(f"Response text: {len(response_text)} chars")
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

    def get_resume_message(self, session) -> dict:
        """
        Get a welcome-back message summarizing session progress.

        Args:
            session: AssistantSession instance

        Returns:
            dict with contextual resume message and quick replies
        """
        summary = session.get_progress_summary()
        message = f"Welcome back! {summary} Would you like to continue?"

        quick_replies = [
            {
                "label": "Continue where I left off",
                "value": "Let's continue where we left off.",
            },
            {"label": "Start over", "value": "I want to start fresh."},
        ]

        return {
            "message": message,
            "follow_up": None,
            "input_type": None,
            "editor_field": None,
            "quick_replies": quick_replies,
            "field_updates": None,
            "complete": session.is_complete,
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
                "Hi! I'm here to help you create a research proposal on ResearchHub. "
                "Do you have an existing draft, or would you like to start fresh?"
            )
            quick_replies = [
                {
                    "label": "Review my draft",
                    "value": "I have an existing draft I'd like to use",
                },
                {
                    "label": "Create a new proposal",
                    "value": "I want to start a new proposal from scratch",
                },
            ]
        else:  # funder
            message = (
                "Hi! I'm here to help you create a funding opportunity on ResearchHub. "
                "Do you have an existing draft, or would you like to start fresh?"
            )
            quick_replies = [
                {
                    "label": "Review my draft",
                    "value": "I have an existing draft I'd like to use",
                },
                {
                    "label": "Create a new funding opportunity",
                    "value": "I want to start a new RFP from scratch",
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
