"""Django-backed recorder tests for persisted agent transcripts."""

from django.test import TestCase

from research_ai.models import AgentConversation, AgentMessage
from research_ai.services.agent.types import Message, TextBlock, ToolResultBlock
from research_ai.services.agent_transcript import DatabaseAgentRecorder


class DatabaseAgentRecorderTests(TestCase):
    def test_record_message_caps_oversized_strings(self):
        # Arrange
        conversation = AgentConversation.objects.create(
            kind=AgentConversation.Kind.PROPOSAL_DRAFT,
            system_prompt="sys",
        )
        recorder = DatabaseAgentRecorder(conversation, max_string_chars=5)
        message = Message(
            role="user",
            content=[
                TextBlock(text="abcdef"),
                ToolResultBlock(
                    tool_use_id="tool-1",
                    content={"nested": {"payload": "ghijkl"}},
                ),
            ],
        )

        # Act
        recorder.record_message(message)

        # Assert
        stored = AgentMessage.objects.get()
        self.assertEqual(stored.content[0]["text"], "abcde")
        self.assertTrue(stored.content[0]["truncated"])
        self.assertEqual(stored.content[1]["content"]["nested"]["payload"], "ghijk")
        self.assertTrue(stored.content[1]["truncated"])
        self.assertTrue(stored.content[1]["content"]["nested"]["truncated"])
