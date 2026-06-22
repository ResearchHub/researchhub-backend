"""Provider-agnostic tool layer for the agent core.

Generalizes the prior ``OpenAlexToolset`` (``tool_specs`` + ``dispatch``) into a
reusable pair of types:

- ``Tool`` -- a named, JSON-Schema-described callable. The agent owns judgment;
  tools own ground truth.
- ``Toolset`` -- a registry that dispatches a tool call and renders its specs to
  a provider's wire format.

Best-effort contract (carried over from the prior art): handlers **never raise**.
A handler returns a plain dict; failures are reported as ``{"error": ...}`` so a
transient miss is handed back to the model rather than aborting the run. The
``Toolset`` also catches any exception a handler does leak and converts it to the
same ``{"error": ...}`` shape.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from research_ai.services.agent.providers.base import LLMProvider

logger = logging.getLogger(__name__)

# Handler signature: receives the model's parsed tool input, returns a dict.
ToolHandler = Callable[[dict], dict]


@dataclass
class Tool:
    """A single tool the model can call.

    Args:
        name: Tool name the model references.
        description: What the tool does (shown to the model).
        input_schema: JSON Schema describing the tool's input object.
        handler: ``(input: dict) -> dict``. Never raises; reports failures as
            ``{"error": ...}``.
        is_terminal: When True, a successful call ends the loop (a "submit"
            tool that hands back a final answer).
    """

    name: str
    description: str
    input_schema: dict
    handler: ToolHandler
    is_terminal: bool = False


class Toolset:
    """A registry of ``Tool``s that dispatches calls and renders specs."""

    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.add(tool)

    def add(self, tool: Tool) -> Tool:
        """Register ``tool`` (replacing any existing tool with the same name)."""
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        """Return the tool named ``name``, or None if it is not registered."""
        return self._tools.get(name)

    @property
    def names(self) -> list[str]:
        """Registered tool names, in insertion order."""
        return list(self._tools)

    @property
    def tools(self) -> list[Tool]:
        """Registered tools, in insertion order."""
        return list(self._tools.values())

    def dispatch(self, name: str, input: dict) -> tuple[dict, bool]:
        """Run a tool call.

        Returns ``(result, stop)``. Unknown tool ->
        ``({"error": "unknown tool: ..."}, False)``. A handler that raises is
        caught and logged -> ``({"error": str(exc)}, False)``. A terminal tool
        returns ``stop=True`` so the loop ends after its result is delivered.
        """
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"unknown tool: {name}"}, False
        try:
            result = tool.handler(input or {})
        except Exception as exc:  # noqa: BLE001 - tool errors go back to the model
            logger.info("tool %r failed: %s", name, exc)
            return {"error": str(exc)}, False
        return result, tool.is_terminal

    def render_specs(self, provider: "LLMProvider") -> Any:
        """Render this toolset to ``provider``'s wire format."""
        return provider.render_tools(self.tools)
