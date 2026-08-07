"""Ambient liveness reporting, attached to the thing that is actually slow.

A recorder that can be pre-empted from outside its run (see
``AgentRecorder.heartbeat``) has to report itself alive at least as often as
whatever reclaims silent runs allows. The loop's own writes cover the turns *it*
drives, and that is not everything: a tool handler can itself call a provider --
proposal drafting judges each submitted draft that way, several sequential calls
deep -- and between the handler being entered and returning, the loop writes
nothing at all. Every fix that instead teaches one more caller to report has the
same shape, and the next long tool reopens the hole.

So the report hangs off the provider call, which is the only thing in this stack
that is slow enough to matter. :class:`Agent` installs the running recorder's
reporter for the duration of a run and every adapter's ``complete`` touches it,
wherever in the call stack that call was made -- inside the loop, inside a tool
handler, or inside a nested agent run. The bound on legitimate silence is then
one provider call, everywhere, by construction rather than by convention.

This module carries the reporter and nothing else: what a touch *does* is the
persistence layer's business, and keeping it opaque is what lets the agent core
stay free of Django.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# A context variable rather than a plain global: it scopes the reporter to the
# thread or task driving one run, so concurrent runs in one process cannot
# report each other alive, and a nested run's reporter cannot outlive it.
_reporter: ContextVar[Callable[[], object] | None] = ContextVar(
    "agent_liveness_reporter", default=None
)


@contextmanager
def reporting_to(reporter: Callable[[], object] | None) -> Iterator[None]:
    """Route :func:`touch` to ``reporter`` for the duration of the block.

    ``None`` is accepted and means "nothing to report to", so callers can pass
    an optional hook straight through without branching. Nests: the previous
    reporter is restored on exit, which is what an agent run started from inside
    a tool handler relies on.
    """
    token = _reporter.set(reporter)
    try:
        yield
    finally:
        _reporter.reset(token)


def touch() -> None:
    """Report that the run owning this context is still alive.

    Best-effort in both directions: no reporter installed is the ordinary case
    for a run nobody is tracking, and a reporter that raises is logged and
    ignored. Liveness reporting is an observation of a run, so it must never be
    able to break one.
    """
    reporter = _reporter.get()
    if reporter is None:
        return
    try:
        reporter()
    except Exception:  # noqa: BLE001 - an observation cannot break the run
        logger.warning("agent liveness reporter failed", exc_info=True)
