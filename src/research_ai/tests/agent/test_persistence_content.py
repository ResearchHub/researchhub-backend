"""Pure unit coverage for bounded agent persistence serialization."""

from unittest import TestCase

from research_ai.services.agent.types import Message, TextBlock, ToolUseBlock
from research_ai.services.agent_persistence.content import (
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

    def test_trace_uses_one_marker_when_size_limit_is_hit(self):
        # Arrange
        text = "x" * MAX_TRACE_MESSAGE_BYTES
        block_count = 10
        message = Message(
            role="assistant",
            content=[TextBlock(text=text) for _ in range(block_count)],
        )

        # Act
        content, is_truncated, _original_size = serialize_trace_message(message)

        # Assert
        markers = [block for block in content if block["type"] == "trace_truncated"]
        retained_block_count = len(content) - len(markers)
        self.assertTrue(is_truncated)
        self.assertEqual(len(markers), 1)
        self.assertEqual(
            markers[0]["omitted_blocks"],
            block_count - retained_block_count,
        )

    def test_context_keeps_many_blocks_when_they_fit_the_byte_limit(self):
        # Arrange
        block_count = 501
        message = Message(
            role="user",
            content=[TextBlock(text="x") for _ in range(block_count)],
        )

        # Act
        content, is_compacted, original_size = serialize_context_message(message)

        # Assert
        self.assertFalse(is_compacted)
        self.assertEqual(original_size, block_count)
        self.assertEqual(len(content), block_count)

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
