"""Unit tests for the Bedrock Converse provider adapter (no network)."""

from copy import deepcopy

from django.test import SimpleTestCase

from research_ai.services.agent.providers.bedrock import BedrockProvider
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    Message,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


class FakeConverseClient:
    """Returns queued Converse responses; records the kwargs it was sent."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        return self._responses.pop(0)


def _provider(responses=None):
    # Inject a fake client so no AWS client is constructed.
    return BedrockProvider(
        client=FakeConverseClient(responses or []), model_id="test-model"
    )


class RenderToolsTests(SimpleTestCase):
    def test_render_tools_produces_tool_spec_shape(self):
        # Arrange
        provider = _provider()
        tool = Tool(
            name="search",
            description="search things",
            input_schema={"type": "object", "properties": {}},
            handler=lambda input: {},
        )

        # Act
        rendered = provider.render_tools([tool])

        # Assert
        self.assertEqual(
            rendered,
            {
                "tools": [
                    {
                        "toolSpec": {
                            "name": "search",
                            "description": "search things",
                            "inputSchema": {
                                "json": {"type": "object", "properties": {}}
                            },
                        }
                    }
                ]
            },
        )


class RenderMessagesTests(SimpleTestCase):
    def test_blocks_render_to_converse_wire_shapes(self):
        # Arrange
        provider = _provider()
        messages = [
            Message(role="user", content=[TextBlock(text="hi")]),
            Message(
                role="assistant",
                content=[ToolUseBlock(id="t1", name="search", input={"q": 1})],
            ),
            Message(
                role="user",
                content=[
                    ToolResultBlock(
                        tool_use_id="t1", content={"ok": True}, is_error=False
                    ),
                    ToolResultBlock(
                        tool_use_id="t2", content={"error": "x"}, is_error=True
                    ),
                ],
            ),
        ]

        # Act
        rendered = provider._render_messages(messages)

        # Assert: text, toolUse, and toolResult shapes (with error status).
        self.assertEqual(rendered[0]["content"][0], {"text": "hi"})
        self.assertEqual(
            rendered[1]["content"][0],
            {"toolUse": {"toolUseId": "t1", "name": "search", "input": {"q": 1}}},
        )
        self.assertEqual(
            rendered[2]["content"][0],
            {"toolResult": {"toolUseId": "t1", "content": [{"json": {"ok": True}}]}},
        )
        self.assertEqual(rendered[2]["content"][1]["toolResult"]["status"], "error")


class CompleteAndParseTests(SimpleTestCase):
    def test_complete_parses_text_and_tool_use_and_stop_reason(self):
        # Arrange
        response = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"text": "let me search"},
                        {
                            "toolUse": {
                                "toolUseId": "t1",
                                "name": "search",
                                "input": {"q": "jane"},
                            }
                        },
                    ],
                }
            },
            "stopReason": "tool_use",
        }
        provider = _provider([response])

        # Act
        turn = provider.complete(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools={"tools": [{"toolSpec": {"name": "search"}}]},
            max_tokens=100,
            temperature=0.0,
        )

        # Assert
        self.assertEqual(turn.text, "let me search")
        self.assertEqual(len(turn.tool_calls), 1)
        self.assertEqual(turn.tool_calls[0].id, "t1")
        self.assertEqual(turn.tool_calls[0].input, {"q": "jane"})
        self.assertEqual(turn.stop_reason, StopReason.TOOL_USE)
        # toolConfig was forwarded because tools were present.
        self.assertIn("toolConfig", provider._client.calls[0])

    def test_parse_turn_maps_unknown_stop_reason_to_other(self):
        # Arrange
        provider = _provider()
        response = {
            "output": {"message": {"role": "assistant", "content": []}},
            "stopReason": "something_new",
        }

        # Act
        turn = provider._parse_turn(response)

        # Assert
        self.assertEqual(turn.stop_reason, StopReason.OTHER)

    def test_missing_output_message_raises(self):
        # Arrange
        provider = _provider([{"stopReason": "end_turn"}])

        # Act / Assert
        with self.assertRaises(RuntimeError):
            provider.complete(
                system_prompt="sys",
                messages=[Message(role="user", content=[TextBlock(text="hi")])],
                rendered_tools={"tools": []},
                max_tokens=100,
                temperature=0.0,
            )
