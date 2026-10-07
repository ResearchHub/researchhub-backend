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

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from research_ai.services.agent.types import ImageBlock

if TYPE_CHECKING:
    from research_ai.services.agent.providers.base import LLMProvider

logger = logging.getLogger(__name__)

# Backstop on one tool result (~32k tokens). Tools are expected to bound their
# own output to something the context window can afford -- a page of results, a
# capped slice of a document -- and every one of ours does. This catches the one
# that forgets: without it an unbounded result floods the context, costs a turn's
# budget, and outgrows the row it has to be stored in to resume the run.
MAX_TOOL_RESULT_BYTES = 128 * 1024
# Backstop on the images one result shows the model; each costs up to ~5K tokens.
MAX_TOOL_RESULT_IMAGES = 20


@dataclass(frozen=True)
class ToolOutput:
    """A tool result that also shows the model images."""

    content: dict
    images: tuple[ImageBlock, ...] = ()


# Handler signature: receives the model's parsed tool input, returns a dict, or
# a ``ToolOutput`` when the result carries images.
ToolHandler = Callable[[dict], "dict | ToolOutput"]


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
        eager_input_streaming: Ask supporting providers to emit input fragments
            before the complete argument is available, for live draft previews.
    """

    name: str
    description: str
    input_schema: dict
    handler: ToolHandler
    is_terminal: bool = False
    eager_input_streaming: bool = False


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
        """Run a tool call; ``call`` without the result's images."""
        output, stop = self.call(name, input)
        return output.content, stop

    def call(self, name: str, input: dict) -> tuple[ToolOutput, bool]:
        """Run a tool call.

        Returns ``(output, stop)``. Unknown tool ->
        ``({"error": "unknown tool: ..."}, False)``. A handler that raises is
        caught and logged -> ``({"error": str(exc)}, False)``. A terminal tool
        returns ``stop=True`` after a non-error result so the loop ends after
        its result is delivered. An error result carries no images.

        ``InterruptedError`` is the exception: it says the *run* should stop, not
        that the tool failed, so handing it back as a retryable error would have
        the model try again against a run nobody is waiting for. It propagates,
        as it does out of a provider call.
        """
        tool = self._tools.get(name)
        if tool is None:
            return _error(f"unknown tool: {name}")
        try:
            result = tool.handler(input or {})
        except InterruptedError:
            raise
        except Exception as exc:  # noqa: BLE001 - tool errors go back to the model
            # A leaked exception is a bug in a handler (they promise not to
            # raise): keep the traceback, and never hand the model an empty
            # error string (some exceptions str() to "").
            logger.warning("tool %r failed", name, exc_info=True)
            return _error(str(exc) or type(exc).__name__)
        images: tuple[ImageBlock, ...] = ()
        if isinstance(result, ToolOutput):
            result, images = result.content, tuple(result.images)
        if not isinstance(result, dict):
            logger.warning(
                "tool %r returned %s instead of dict", name, type(result).__name__
            )
            return _error(
                f"tool {name!r} returned {type(result).__name__}; expected dict"
            )
        try:
            encoded = json.dumps(result, allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            logger.warning("tool %r returned invalid JSON", name, exc_info=True)
            return _error(f"tool {name!r} returned invalid JSON")
        size = len(encoded.encode("utf-8"))
        if size > MAX_TOOL_RESULT_BYTES:
            # Reported to the model, not truncated for it: it can narrow the
            # query or page through the result, which a silent slice of someone
            # else's JSON would deny it.
            logger.warning("tool %r returned %d bytes, over the limit", name, size)
            return _error(
                f"tool {name!r} returned {size} bytes, over the "
                f"{MAX_TOOL_RESULT_BYTES} byte limit; request less at a time"
            )
        if not all(isinstance(image, ImageBlock) for image in images):
            logger.warning("tool %r returned images that are not ImageBlocks", name)
            return _error(f"tool {name!r} returned invalid images")
        if len(images) > MAX_TOOL_RESULT_IMAGES:
            logger.warning("tool %r returned %d images", name, len(images))
            return _error(
                f"tool {name!r} returned {len(images)} images, over the "
                f"{MAX_TOOL_RESULT_IMAGES} image limit; request fewer at a time"
            )
        is_error = "error" in result
        return (
            ToolOutput(content=result, images=() if is_error else images),
            tool.is_terminal and not is_error,
        )

    def render_specs(self, provider: "LLMProvider") -> Any:
        """Render this toolset to ``provider``'s wire format."""
        return provider.render_tools(self.tools)


def _error(message: str) -> tuple[ToolOutput, bool]:
    return ToolOutput(content={"error": message}), False
