"""Pure unit coverage for bounded agent persistence serialization."""

from unittest import TestCase

from research_ai.services.agent.types import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    deserialize_messages,
    serialize_messages,
)
from research_ai.services.agent_persistence.content import (
    MAX_BLOCK_PAYLOAD_BYTES,
    MAX_CONTEXT_MESSAGE_BYTES,
    MAX_TRACE_MESSAGE_BYTES,
    bounded_payload,
    json_size_bytes,
    serialize_context_message,
    serialize_final_output,
    serialize_trace_message,
)


class AgentPersistenceContentTests(TestCase):
    def test_bounded_payload_keeps_native_json(self):
        # Arrange
        value = {"enabled": True, "items": [1, "two", None]}

        # Act
        safe, was_replaced, original_size = bounded_payload(value)

        # Assert
        self.assertFalse(was_replaced)
        self.assertEqual(safe, value)
        self.assertEqual(original_size, json_size_bytes(value))

    def test_bounded_payload_replaces_invalid_json(self):
        # Arrange
        value = {"raw": b"not json"}

        # Act
        safe, was_replaced, original_size = bounded_payload(value)

        # Assert
        self.assertTrue(was_replaced)
        self.assertEqual(safe, {"_serialization_error": True})
        self.assertEqual(original_size, 0)

    def test_bounded_payload_replaces_non_native_json(self):
        # Arrange
        value = {"items": (1, 2)}

        # Act
        safe, was_replaced, original_size = bounded_payload(value)

        # Assert
        self.assertTrue(was_replaced)
        self.assertEqual(safe, {"_serialization_error": True})
        self.assertEqual(original_size, json_size_bytes(value))

    def test_bounded_payload_replaces_oversized_json(self):
        # Arrange
        value = {"body": "x" * MAX_BLOCK_PAYLOAD_BYTES}

        # Act
        safe, was_replaced, original_size = bounded_payload(value)

        # Assert
        self.assertTrue(was_replaced)
        self.assertTrue(safe["_truncated"])
        self.assertEqual(safe["original_size_bytes"], original_size)
        self.assertLessEqual(len(safe["preview"]), 2048)
        self.assertLessEqual(json_size_bytes(safe), MAX_BLOCK_PAYLOAD_BYTES)

    def test_trace_keeps_complete_message_within_limit(self):
        # Arrange
        message = Message(role="assistant", content=[TextBlock(text="complete")])
        blocks = serialize_messages([message])[0]["content"]

        # Act
        content, is_truncated, original_size = serialize_trace_message(message)

        # Assert
        self.assertFalse(is_truncated)
        self.assertEqual(content, blocks)
        self.assertEqual(original_size, json_size_bytes(blocks))

    def test_trace_replaces_complete_message_over_limit(self):
        # Arrange
        block_count = 3
        message = Message(
            role="assistant",
            content=[
                TextBlock(text="x" * MAX_TRACE_MESSAGE_BYTES)
                for _ in range(block_count)
            ],
        )
        blocks = serialize_messages([message])[0]["content"]

        # Act
        content, is_truncated, original_size = serialize_trace_message(message)

        # Assert
        self.assertTrue(is_truncated)
        self.assertEqual(content[0]["type"], "text")
        self.assertTrue(content[0]["_truncated"])
        self.assertEqual(content[0]["omitted_blocks"], block_count)
        self.assertEqual(original_size, json_size_bytes(blocks))
        self.assertLessEqual(json_size_bytes(content), MAX_TRACE_MESSAGE_BYTES)
        deserialize_messages([{"role": message.role, "content": content}])

    def test_context_keeps_complete_message_within_limit(self):
        # Arrange
        message = Message(
            role="user",
            content=[TextBlock(text="x") for _ in range(501)],
        )
        blocks = serialize_messages([message])[0]["content"]

        # Act
        content, provider_state, is_compacted, original_size = (
            serialize_context_message(message)
        )

        # Assert
        self.assertFalse(is_compacted)
        self.assertEqual(content, blocks)
        self.assertEqual(provider_state, {})
        self.assertEqual(
            original_size,
            json_size_bytes({"content": blocks, "provider_state": {}}),
        )

    def test_context_keeps_provider_state_for_resume(self):
        # Arrange: Claude's request-level container state must survive beside
        # the assistant content that created it.
        message = Message(
            role="assistant",
            content=[TextBlock(text="working")],
            provider_state={
                "anthropic": {
                    "container": {
                        "id": "container_123",
                        "expires_at": "2026-07-29T21:30:00Z",
                    }
                }
            },
        )

        # Act
        content, provider_state, is_compacted, _ = serialize_context_message(message)
        restored = deserialize_messages(
            [
                {
                    "role": message.role,
                    "content": content,
                    "provider_state": provider_state,
                }
            ]
        )[0]

        # Assert
        self.assertFalse(is_compacted)
        self.assertEqual(restored, message)

    def test_context_compacts_complete_message_over_limit(self):
        # Arrange
        message = Message(
            role="assistant",
            content=[
                ToolUseBlock(
                    id="call-1",
                    name="lookup",
                    input={"body": "x" * MAX_CONTEXT_MESSAGE_BYTES},
                )
            ],
        )
        blocks = serialize_messages([message])[0]["content"]

        # Act
        content, provider_state, is_compacted, original_size = (
            serialize_context_message(message)
        )

        # Assert
        self.assertTrue(is_compacted)
        self.assertEqual(content[0]["type"], "tool_use")
        self.assertEqual(content[0]["id"], "call-1")
        self.assertEqual(content[0]["name"], "lookup")
        self.assertTrue(content[0]["input"]["_truncated"])
        self.assertEqual(provider_state, {})
        self.assertEqual(
            original_size,
            json_size_bytes({"content": blocks, "provider_state": {}}),
        )
        self.assertLessEqual(json_size_bytes(content), MAX_CONTEXT_MESSAGE_BYTES)
        deserialize_messages([{"role": message.role, "content": content}])

    def test_context_compaction_keeps_tool_results_answering_their_calls(self):
        # Arrange: a tool that returns more than the row limit is the common
        # case, and its result must keep answering the call in the turn before
        # it -- an unpaired tool_use fails every later provider turn.
        call = Message(
            role="assistant",
            content=[
                TextBlock(text="looking that up"),
                ToolUseBlock(id="call-1", name="fetch", input={"doi": "10.1/abc"}),
            ],
        )
        result = Message(
            role="user",
            content=[
                ToolResultBlock(
                    tool_use_id="call-1",
                    content={"body": "x" * MAX_CONTEXT_MESSAGE_BYTES},
                )
            ],
        )

        # Act
        call_content, _state, call_compacted, _size = serialize_context_message(call)
        result_content, _state, result_compacted, _size = serialize_context_message(
            result
        )

        # Assert
        self.assertFalse(call_compacted)
        self.assertTrue(result_compacted)
        restored = deserialize_messages(
            [
                {"role": call.role, "content": call_content},
                {"role": result.role, "content": result_content},
            ]
        )
        self.assertEqual(restored[0], call)
        self.assertEqual(restored[1].content[0].tool_use_id, "call-1")
        self.assertLessEqual(json_size_bytes(result_content), MAX_CONTEXT_MESSAGE_BYTES)

    def test_context_compacts_every_block_when_no_single_block_is_oversized(self):
        # Arrange: each block fits the per-block budget, so only compacting the
        # individually oversized ones would leave the message over the limit.
        body_bytes = MAX_BLOCK_PAYLOAD_BYTES // 2
        block_count = (MAX_CONTEXT_MESSAGE_BYTES // body_bytes) + 2
        message = Message(
            role="assistant",
            content=[
                ToolUseBlock(
                    id=f"call-{index}",
                    name="lookup",
                    input={"body": "x" * body_bytes},
                )
                for index in range(block_count)
            ],
        )

        # Act
        content, _provider_state, is_compacted, _size = serialize_context_message(
            message
        )

        # Assert
        self.assertTrue(is_compacted)
        self.assertEqual(
            [block["id"] for block in content],
            [f"call-{index}" for index in range(block_count)],
        )
        self.assertLessEqual(json_size_bytes(content), MAX_CONTEXT_MESSAGE_BYTES)
        deserialize_messages([{"role": message.role, "content": content}])

    def test_context_compaction_leaves_signed_blocks_byte_for_byte(self):
        # Arrange: adapters replay reasoning payloads unedited, so compacting a
        # neighbouring block must not rewrite one that already fits.
        thinking = ThinkingBlock(data={"signature": "sig-1", "thinking": "weighing"})
        message = Message(
            role="assistant",
            content=[
                thinking,
                ToolUseBlock(
                    id="call-1",
                    name="lookup",
                    input={"body": "x" * MAX_CONTEXT_MESSAGE_BYTES},
                ),
            ],
        )

        # Act
        content, _provider_state, is_compacted, _size = serialize_context_message(
            message
        )

        # Assert
        self.assertTrue(is_compacted)
        restored = deserialize_messages([{"role": message.role, "content": content}])[0]
        self.assertEqual(restored.content[0], thinking)
        self.assertTrue(content[1]["input"]["_truncated"])

    def test_context_falls_back_to_text_when_a_signed_block_cannot_fit(self):
        # Arrange: a marker in place of the signed payload would be rejected on
        # replay, so the message degrades to text the provider still accepts.
        message = Message(
            role="assistant",
            content=[
                ThinkingBlock(
                    data={
                        "signature": "sig-1",
                        "thinking": "x" * MAX_CONTEXT_MESSAGE_BYTES,
                    }
                )
            ],
        )

        # Act
        content, _provider_state, is_compacted, _size = serialize_context_message(
            message
        )

        # Assert
        self.assertTrue(is_compacted)
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["type"], "text")
        self.assertLessEqual(json_size_bytes(content), MAX_CONTEXT_MESSAGE_BYTES)
        deserialize_messages([{"role": message.role, "content": content}])

    def test_context_falls_back_to_text_when_state_alone_is_oversized(self):
        # Arrange: nothing about the message can be compacted into the row, so
        # structure and the state describing it are dropped together.
        message = Message(
            role="assistant",
            content=[TextBlock(text="done")],
            provider_state={"blob": "x" * (MAX_CONTEXT_MESSAGE_BYTES * 2)},
        )

        # Act
        content, provider_state, is_compacted, _size = serialize_context_message(
            message
        )

        # Assert
        self.assertTrue(is_compacted)
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(provider_state, {})
        self.assertLessEqual(json_size_bytes(content), MAX_CONTEXT_MESSAGE_BYTES)
        deserialize_messages([{"role": message.role, "content": content}])

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
