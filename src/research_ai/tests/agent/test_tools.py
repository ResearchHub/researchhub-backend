"""Unit tests for the Tool / Toolset dispatch contract."""

from django.test import SimpleTestCase

from research_ai.services.agent.tools import Tool, Toolset


def _ok_tool(name, *, is_terminal=False):
    return Tool(
        name=name,
        description=name,
        input_schema={"type": "object"},
        handler=lambda input: {"echo": input},
        is_terminal=is_terminal,
    )


class ToolsetDispatchTests(SimpleTestCase):
    def test_unknown_tool_returns_error_and_no_stop(self):
        # Arrange
        toolset = Toolset([_ok_tool("search")])

        # Act
        result, stop = toolset.dispatch("nope", {})

        # Assert
        self.assertEqual(result, {"error": "unknown tool: nope"})
        self.assertFalse(stop)

    def test_handler_exception_is_caught_not_raised(self):
        # Arrange: a handler that raises rather than returning {"error": ...}.
        def boom(input):
            raise ValueError("kaboom")

        toolset = Toolset([Tool("explode", "explode", {"type": "object"}, boom)])

        # Act
        result, stop = toolset.dispatch("explode", {})

        # Assert: the exception is converted to an error result, not propagated.
        self.assertEqual(result, {"error": "kaboom"})
        self.assertFalse(stop)

    def test_terminal_tool_signals_stop(self):
        # Arrange
        toolset = Toolset([_ok_tool("submit", is_terminal=True)])

        # Act
        result, stop = toolset.dispatch("submit", {"a": 1})

        # Assert
        self.assertEqual(result, {"echo": {"a": 1}})
        self.assertTrue(stop)

    def test_non_terminal_tool_does_not_stop(self):
        # Arrange
        toolset = Toolset([_ok_tool("search")])

        # Act
        result, stop = toolset.dispatch("search", {"q": "x"})

        # Assert
        self.assertEqual(result, {"echo": {"q": "x"}})
        self.assertFalse(stop)

    def test_registry_accessors(self):
        # Arrange
        search = _ok_tool("search")
        toolset = Toolset([search])

        # Act / Assert
        self.assertEqual(toolset.names, ["search"])
        self.assertIs(toolset.get("search"), search)
        self.assertIsNone(toolset.get("missing"))
