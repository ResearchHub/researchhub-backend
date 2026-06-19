"""Unit tests for BedrockLLMService.run_tool_loop (Converse tool protocol)."""

from copy import deepcopy

from django.test import SimpleTestCase

from research_ai.services.bedrock_llm_service import BedrockLLMService


def _make_service(converse_client):
    """A BedrockLLMService wired to a fake Converse client (no AWS)."""
    service = BedrockLLMService.__new__(BedrockLLMService)
    service.bedrock_client = converse_client
    service.model_id = "test-model"
    return service


def _tool_use(tool_use_id, name, tool_input):
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": tool_use_id,
                            "name": name,
                            "input": tool_input,
                        }
                    }
                ],
            }
        }
    }


def _text(message):
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": message}]}}
    }


class FakeConverseClient:
    """Returns queued Converse responses; records the messages it was sent."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def converse(self, **kwargs):
        # Snapshot kwargs: the loop keeps mutating the same messages list.
        self.calls.append(deepcopy(kwargs))
        return self._responses.pop(0)


class RunToolLoopTests(SimpleTestCase):
    def test_dispatches_tool_then_stops_on_terminal_tool(self):
        # Arrange
        client = FakeConverseClient(
            [
                _tool_use("t1", "search", {"q": "jane"}),
                _tool_use("t2", "submit", {"done": True}),
            ]
        )
        service = _make_service(client)
        seen = []

        def dispatch(name, tool_input):
            seen.append((name, tool_input))
            return {"ok": True}, name == "submit"

        # Act
        service.run_tool_loop(
            "system", "user", tools=[{"toolSpec": {"name": "x"}}], dispatch=dispatch
        )
        # Assert: both tools ran; the loop stopped after the terminal tool.
        self.assertEqual(seen, [("search", {"q": "jane"}), ("submit", {"done": True})])
        # The first tool's result was fed back as a toolResult user message.
        second_call_messages = client.calls[1]["messages"]
        tool_results = second_call_messages[-1]["content"]
        self.assertEqual(tool_results[0]["toolResult"]["toolUseId"], "t1")

    def test_plain_text_response_ends_loop(self):
        # Arrange
        client = FakeConverseClient([_text("all done")])
        service = _make_service(client)
        # Act
        result = service.run_tool_loop(
            "system", "user", tools=[], dispatch=lambda n, i: ({}, False)
        )
        # Assert
        self.assertEqual(result, "all done")

    def test_exceeding_max_iterations_raises(self):
        # Arrange: the model never stops calling tools.
        client = FakeConverseClient([_tool_use(f"t{i}", "loop", {}) for i in range(5)])
        service = _make_service(client)
        # Act / Assert
        with self.assertRaises(RuntimeError):
            service.run_tool_loop(
                "system",
                "user",
                tools=[],
                dispatch=lambda n, i: ({}, False),
                max_iterations=3,
            )
