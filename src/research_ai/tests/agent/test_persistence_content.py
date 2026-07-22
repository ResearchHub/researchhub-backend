"""Pure unit coverage for bounded agent persistence serialization."""

from unittest import TestCase

from research_ai.services.agent.types import Message, TextBlock, ToolUseBlock
from research_ai.services.agent_persistence.content import (
    MAX_COLLECTION_ITEMS,
    MAX_CONTEXT_BLOCK_PAYLOAD_BYTES,
    MAX_TRACE_MESSAGE_BYTES,
    serialize_context_message,
    serialize_final_output,
    serialize_trace_message,
)
from utils.json import json_size_bytes


class AgentPersistenceContentTests(TestCase):
    def test_trace_text_is_bounded_by_serialized_bytes(self):
        # Arrange
        text = "🧪" * MAX_TRACE_MESSAGE_BYTES
        message = Message(role="assistant", content=[TextBlock(text=text)])

        # Act
        content, is_truncated, original_size = serialize_trace_message(message)

        # Assert
        self.assertTrue(is_truncated)
        self.assertEqual(original_size, len(text.encode("utf-8")))
        self.assertLessEqual(json_size_bytes(content), MAX_TRACE_MESSAGE_BYTES)

    def test_context_with_excessive_blocks_compacts_before_serialization(self):
        # Arrange
        message = Message(
            role="user",
            content=[TextBlock(text="x") for _ in range(MAX_COLLECTION_ITEMS + 1)],
        )

        # Act
        content, is_compacted, original_size = serialize_context_message(message)

        # Assert
        self.assertTrue(is_compacted)
        self.assertIsNone(original_size)
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["type"], "text")

    def test_large_context_payload_keeps_a_typed_tool_block(self):
        # Arrange
        message = Message(
            role="assistant",
            content=[
                ToolUseBlock(
                    id="call-1",
                    name="lookup",
                    input={"body": "x" * (MAX_CONTEXT_BLOCK_PAYLOAD_BYTES * 2)},
                )
            ],
        )

        # Act
        content, is_compacted, original_size = serialize_context_message(message)

        # Assert
        self.assertTrue(is_compacted)
        self.assertGreater(original_size, MAX_CONTEXT_BLOCK_PAYLOAD_BYTES)
        self.assertEqual(content[0]["type"], "tool_use")

    def test_final_output_remains_repairable_when_truncated(self):
        # Arrange
        text = "x" * (MAX_TRACE_MESSAGE_BYTES * 2)

        # Act
        output, is_truncated, original_size = serialize_final_output(text)

        # Assert
        self.assertTrue(is_truncated)
        self.assertEqual(original_size, len(text.encode("utf-8")))
        self.assertIsInstance(output["text"], str)
        self.assertTrue(output["_truncated"])
        self.assertLessEqual(json_size_bytes(output), MAX_TRACE_MESSAGE_BYTES)
