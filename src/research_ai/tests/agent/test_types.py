"""Unit tests for the neutral agent types and their JSON round-trip."""

from django.test import SimpleTestCase

from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    deserialize_messages,
    serialize_messages,
)


class TypesTests(SimpleTestCase):
    def test_serialize_deserialize_round_trips_every_block_type(self):
        # Arrange: a conversation containing all three block types.
        messages = [
            Message(role="user", content=[TextBlock(text="find jane")]),
            Message(
                role="assistant",
                content=[
                    TextBlock(text="searching"),
                    ToolUseBlock(id="t1", name="search", input={"q": "jane"}),
                ],
            ),
            Message(
                role="user",
                content=[
                    ToolResultBlock(
                        tool_use_id="t1",
                        content={"results": [1, 2]},
                        is_error=False,
                    ),
                    ToolResultBlock(
                        tool_use_id="t2",
                        content={"error": "boom"},
                        is_error=True,
                    ),
                ],
            ),
        ]

        # Act
        round_tripped = deserialize_messages(serialize_messages(messages))

        # Assert: equality is preserved across the JSON round-trip.
        self.assertEqual(round_tripped, messages)

    def test_serialized_shape_carries_type_discriminator(self):
        # Arrange
        messages = [
            Message(
                role="assistant",
                content=[ToolUseBlock(id="t1", name="search", input={"q": 1})],
            )
        ]

        # Act
        data = serialize_messages(messages)

        # Assert
        block = data[0]["content"][0]
        self.assertEqual(block["type"], "tool_use")
        self.assertEqual(block["id"], "t1")
        self.assertEqual(block["name"], "search")
        self.assertEqual(block["input"], {"q": 1})

    def test_assistant_turn_text_joins_text_blocks(self):
        # Arrange
        turn = AssistantTurn(
            text_blocks=[TextBlock(text="he"), TextBlock(text="llo")],
            tool_calls=[],
            stop_reason=StopReason.END_TURN,
        )

        # Act / Assert
        self.assertEqual(turn.text, "hello")
