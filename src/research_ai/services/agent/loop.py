"""The agent loop: drives multi-turn, tool-using conversations to completion.

This is the neutral generalization of ``BedrockLLMService.run_tool_loop``. It
renders the toolset once, then repeatedly asks the provider to ``complete`` a
turn, dispatching every tool call the model makes and feeding the results back
until the model answers in plain text or a terminal tool stops the run.

The loop is resumable: ``continue_conversation`` appends a user turn to an
existing message list and drives from there, which is what a notebook-style
multi-turn chat needs.
"""

import logging
from dataclasses import dataclass

from research_ai.services.agent import heartbeat
from research_ai.services.agent.errors import (
    AgentRunError,
    IncompleteTurnError,
    IterationLimitError,
    ProviderError,
)
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.recorder import AgentRecorder
from research_ai.services.agent.tools import Toolset
from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
    ServerToolBlock,
    StopReason,
    TextBlock,
    ToolResultBlock,
)

logger = logging.getLogger(__name__)

# Cap on how much of any single value the trace logs, so a large tool input
# (e.g. a full proposal submission) or result never floods the log.
_LOG_VALUE_LIMIT = 300


def _truncate(text: str, limit: int = _LOG_VALUE_LIMIT) -> str:
    """Collapse whitespace and cap ``text`` to ``limit`` chars for one-line logs."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"


def _compact_args(args) -> str:
    """One-line, length-capped view of a tool call's input for tracing.

    Strings are truncated, and lists/dicts are shown by size/keys rather than
    dumped, so the "what was called with" reads at a glance without logging a
    whole proposal body or works list.
    """
    if not isinstance(args, dict):
        return _truncate(repr(args))
    parts = []
    for key, value in args.items():
        if isinstance(value, str):
            shown = _truncate(value, 80)
        elif isinstance(value, (list, tuple)):
            shown = f"[{len(value)} items]"
        elif isinstance(value, dict):
            shown = "{" + ", ".join(map(str, value.keys())) + "}"
        else:
            shown = repr(value)
        parts.append(f"{key}={shown}")
    return _truncate(", ".join(parts))


def _summarize_result(result) -> str:
    """One-line summary of a tool result: error text, or the dict's shape."""
    if isinstance(result, dict):
        if "error" in result:
            return f"error: {_truncate(result['error'], 120)}"
        return "{" + ", ".join(map(str, result.keys())) + "}"
    if isinstance(result, (list, tuple)):
        return f"[{len(result)} items]"
    return _truncate(repr(result))


def _server_tool_name(data: dict) -> str:
    """Tool name recovered from a server-side result block's type."""
    return str(data.get("type") or "server_tool").removesuffix("_tool_result")


def _summarize_server_result(content) -> str:
    """One-line summary of a server-side tool result.

    Search success carries a list of records, while other server tools return
    typed dictionaries. Only an explicit ``error_code`` is an error. Successful
    dictionaries are summarized from safe structural metadata so opaque replay
    fields such as encrypted stdout never reach logs.
    """
    if isinstance(content, dict):
        error_code = content.get("error_code")
        if error_code:
            return f"error: {_truncate(error_code, 120)}"

        result_type = str(content.get("type") or "result")
        details = []
        if "return_code" in content:
            details.append(f"return_code={content['return_code']}")
        outputs = content.get("content")
        if isinstance(outputs, (list, tuple)):
            details.append(f"outputs={len(outputs)}")
        return f"{result_type} ({', '.join(details)})" if details else result_type
    if isinstance(content, (list, tuple)):
        return f"[{len(content)} results]"
    return _truncate(repr(content))


@dataclass
class AgentResult:
    """The outcome of an agent run.

    Args:
        messages: The full conversation, ready to persist or resume.
        final_text: The assistant's last text (often empty when it ends on a
            terminal tool call).
        stop_reason: ``"end_turn"`` (model answered in plain text) or
            ``"stop_tool"`` (a terminal tool ended the run).
        iterations: Number of model turns taken.
    """

    messages: list[Message]
    final_text: str
    stop_reason: str
    iterations: int


class Agent:
    """Drives a provider + toolset over multiple turns until completion."""

    def __init__(
        self,
        provider: LLMProvider,
        toolset: Toolset,
        *,
        system_prompt: str,
        max_iterations: int,
        max_tokens: int,
        temperature: float,
        recorder: AgentRecorder | None = None,
    ):
        self.provider = provider
        self.toolset = toolset
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.recorder = recorder

    def run(self, user_prompt: str) -> AgentResult:
        """Drive a fresh conversation from ``user_prompt`` to completion."""
        seed = Message(role="user", content=[TextBlock(text=user_prompt)])
        return self._drive([seed], new_message=seed)

    def continue_conversation(
        self,
        messages: list[Message],
        user_message: str,
    ) -> AgentResult:
        """Append a user turn to ``messages`` and drive (resumable multi-turn).

        ``messages`` is copied, not mutated; the updated list is returned on the
        ``AgentResult``. Only the appended turn is recorded -- the history was
        recorded by the runs that produced it.
        """
        appended = Message(role="user", content=[TextBlock(text=user_message)])
        return self._drive(list(messages) + [appended], new_message=appended)

    def _record_message(
        self, message: Message, *, turn: AssistantTurn | None = None
    ) -> None:
        """Persist an appended message before the run advances.

        Ordinary observers remain best-effort. A recorder may opt into required
        message persistence with ``requires_durable_messages``; the database
        recorder uses that contract while isolating its optional trace writes.
        """
        if self.recorder is None:
            return
        try:
            self.recorder.record_message(message, turn=turn)
        except Exception:  # noqa: BLE001 - observer failures are best-effort
            if getattr(self.recorder, "requires_durable_messages", False):
                raise
            logger.warning("agent recorder record_message failed", exc_info=True)

    def _ensure_active(self) -> None:
        """Stop before a tool call if this run no longer owns its execution.

        Every other stop point is a write, and writes happen *after* the tool
        has already run. A turn cancelled between recording its tool calls and
        dispatching them would still edit the note, and cancellation frees the
        conversation immediately, so that edit could land beside the turn the
        user sent instead -- both writing the same document.

        The check is optional (see ``AgentRecorder.is_active``) and its failure
        is not a stop signal: a recorder that cannot answer must not be able to
        halt a healthy run.
        """
        is_active = getattr(self.recorder, "is_active", None)
        if is_active is None:
            return
        try:
            active = is_active()
        except Exception:  # noqa: BLE001 - an unanswerable check is not a stop
            logger.warning("agent recorder is_active failed", exc_info=True)
            return
        if not active:
            raise InterruptedError("agent execution is no longer running")

    def _record_terminal(self, hook: str, *args) -> None:
        """Best-effort terminal observation must not mask the run outcome."""
        if self.recorder is None:
            return
        try:
            getattr(self.recorder, hook)(*args)
        except Exception:  # noqa: BLE001 - preserve the original run outcome
            logger.warning("agent recorder %s failed", hook, exc_info=True)

    def _complete_turn(self, messages, rendered_tools, iteration):
        try:
            return self.provider.complete(
                system_prompt=self.system_prompt,
                messages=messages,
                rendered_tools=rendered_tools,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
        except AgentRunError as exc:
            # Attach the transcript so the failure is inspectable and the
            # conversation resumable via ``continue_conversation``.
            exc.messages = messages
            exc.iterations = iteration - 1
            raise
        except InterruptedError:
            # Preserve an explicit interruption so persistence can distinguish
            # it from an ordinary provider failure.
            raise
        except Exception as exc:
            # A provider that leaks a foreign exception still surfaces as
            # the typed contract, transcript attached.
            raise ProviderError(
                f"Provider failed to complete a turn: {exc}",
                messages=messages,
                iterations=iteration - 1,
            ) from exc

    def _log_server_tools(self, turn, iteration: int) -> None:
        """Trace the tools the provider ran inside the turn.

        Server-side calls never reach ``dispatch``, so without this the trace
        would fall silent exactly where it used to show every search -- and a
        provider-run search that returned nothing would be indistinguishable
        from one the model never made.
        """
        for block in turn.content_blocks:
            if not isinstance(block, ServerToolBlock):
                continue
            data = block.data or {}
            if data.get("type") == "server_tool_use":
                logger.info(
                    "iter %d -> %s(%s) [server]",
                    iteration,
                    data.get("name"),
                    _compact_args(data.get("input")),
                )
            else:
                logger.info(
                    "iter %d <- %s: %s [server]",
                    iteration,
                    _server_tool_name(data),
                    _summarize_server_result(data.get("content")),
                )

    def _dispatch_tool_calls(
        self, tool_calls, iteration: int
    ) -> tuple[list[ToolResultBlock], bool]:
        result_blocks: list[ToolResultBlock] = []
        stop = False
        for call in tool_calls:
            # Per call, not once per turn: a turn can ask for several tools, and
            # a cancellation landing partway through must not let the rest run.
            self._ensure_active()
            logger.info(
                "iter %d -> %s(%s)", iteration, call.name, _compact_args(call.input)
            )
            result, tool_stop = self.toolset.dispatch(call.name, call.input)
            logger.info(
                "iter %d <- %s: %s%s",
                iteration,
                call.name,
                _summarize_result(result),
                " [terminal]" if tool_stop else "",
            )
            stop = stop or tool_stop
            result_blocks.append(
                ToolResultBlock(
                    tool_use_id=call.id,
                    content=result,
                    is_error=isinstance(result, dict) and "error" in result,
                )
            )
        return result_blocks, stop

    def _drive(self, messages: list[Message], *, new_message: Message) -> AgentResult:
        # Every provider call made anywhere under this run reports the recorder
        # alive, including calls a tool handler makes itself -- the loop's own
        # writes only cover the turns it drives. See ``agent.heartbeat``.
        with heartbeat.reporting_to(getattr(self.recorder, "heartbeat", None)):
            try:
                self._record_message(new_message)
                result = self._loop(messages)
            except Exception as error:
                # Every message up to the failure was already recorded as it was
                # appended; this only marks the terminal outcome.
                self._record_terminal("on_run_failed", error)
                raise
            self._record_terminal("on_run_finished", result)
            return result

    def _loop(self, messages: list[Message]) -> AgentResult:
        rendered_tools = self.toolset.render_specs(self.provider)
        logger.info(
            "agent run start: tools=[%s] max_iterations=%d",
            ", ".join(self.toolset.names),
            self.max_iterations,
        )

        for iteration in range(1, self.max_iterations + 1):
            turn = self._complete_turn(messages, rendered_tools, iteration)
            # The turn is replayed exactly as the provider sent it: reasoning
            # blocks are signed and must lead, and a server-side tool's result
            # must stay immediately after its request, so the run can neither
            # re-order nor drop blocks here.
            assistant_message = Message(
                role="assistant",
                content=turn.replay_content,
                provider_state=turn.provider_state,
            )
            messages.append(assistant_message)
            self._record_message(assistant_message, turn=turn)

            # The assistant's text on a tool-calling turn is its stated reason for
            # the calls -- log it so the trace shows *why* a tool was picked.
            if turn.text.strip():
                logger.info("iter %d reasoning: %s", iteration, _truncate(turn.text))
            self._log_server_tools(turn, iteration)

            if not turn.tool_calls and turn.stop_reason == StopReason.END_TURN:
                # Model answered in plain text without calling a tool: done.
                logger.info("iter %d end_turn: agent answered in plain text", iteration)
                return AgentResult(
                    messages=messages,
                    final_text=turn.text,
                    stop_reason=turn.stop_reason.value,
                    iterations=iteration,
                )
            if not turn.tool_calls and turn.stop_reason == StopReason.PAUSE_TURN:
                # The provider spent its per-turn budget of server-side tool
                # calls and handed the turn back mid-flight. Nothing is owed in
                # reply: sending the conversation back with this turn appended
                # and no user turn after it resumes where it left off. It counts
                # as an iteration, which is what bounds a pathological pause
                # loop. (A paused turn that *also* called a client tool falls
                # through to the dispatch below -- those results resume it too.)
                logger.info("iter %d pause_turn: resuming server-side work", iteration)
                continue
            if not turn.tool_calls:
                raise IncompleteTurnError(
                    "Provider stopped without completing the agent run: "
                    f"{turn.stop_reason.value}",
                    stop_reason=turn.stop_reason.value,
                    messages=messages,
                    iterations=iteration,
                )

            result_blocks, stop = self._dispatch_tool_calls(turn.tool_calls, iteration)
            tool_result_message = Message(role="user", content=result_blocks)
            messages.append(tool_result_message)
            self._record_message(tool_result_message)

            if stop:
                logger.info("iter %d stop_tool: terminal tool ended the run", iteration)
                return AgentResult(
                    messages=messages,
                    final_text=turn.text,
                    stop_reason="stop_tool",
                    iterations=iteration,
                )

        logger.info("agent hit iteration cap of %d", self.max_iterations)
        raise IterationLimitError(
            f"Agent exceeded {self.max_iterations} iterations",
            messages=messages,
            iterations=self.max_iterations,
        )
