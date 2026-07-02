"""Typed failures for the agent core.

The loop and providers raise these instead of bare ``RuntimeError`` so callers
classify a failed run by exception type, not by string-matching the message.
Each error carries the partial transcript (``messages``) and the number of
completed model turns (``iterations``), so a failed run can be logged,
persisted, or resumed via ``Agent.continue_conversation`` instead of losing
the whole conversation.

All types subclass ``RuntimeError``, so callers still catching the loop's old
``RuntimeError`` contract keep working.
"""

from research_ai.services.agent.types import Message


class AgentRunError(RuntimeError):
    """Base class for agent-run failures.

    Args:
        message: Human-readable description of the failure.
        messages: The partial transcript accumulated before the failure.
        iterations: Model turns completed before the failure.
    """

    def __init__(
        self,
        message: str,
        *,
        messages: list[Message] | None = None,
        iterations: int | None = None,
    ):
        super().__init__(message)
        self.messages = messages if messages is not None else []
        self.iterations = iterations


class ProviderError(AgentRunError):
    """The provider failed to complete a turn (API error, malformed response).

    Providers raise this without a transcript; the loop attaches ``messages``
    and ``iterations`` as the error propagates through it.
    """


class IncompleteTurnError(AgentRunError):
    """The provider returned a turn that neither answered nor called a tool.

    Carries the provider's ``stop_reason`` (e.g. ``"max_tokens"``,
    ``"content_filtered"``) so callers can surface the actionable cause
    instead of a generic provider error.
    """

    def __init__(
        self,
        message: str,
        *,
        stop_reason: str,
        messages: list[Message] | None = None,
        iterations: int | None = None,
    ):
        super().__init__(message, messages=messages, iterations=iterations)
        self.stop_reason = stop_reason


class IterationLimitError(AgentRunError):
    """The loop hit ``max_iterations`` without the run completing."""
