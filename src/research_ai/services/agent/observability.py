"""Optional Datadog LLM Observability hooks for the agent loop.

A thin wrapper around ddtrace's LLM Observability so the loop can emit
``agent``/``tool`` spans without hard-depending on ddtrace being installed or
turned on. When ddtrace is missing or LLM Observability is disabled, every
helper here degrades to a no-op passthrough, so the loop runs unchanged in
local and test environments.

To turn it on in an environment, set the standard Datadog env vars and call
``enable_llm_observability()`` once at startup (done in ``ResearchAIConfig``):

    DD_LLMOBS_ENABLED=1
    DD_LLMOBS_ML_APP=research-ai            # logical app name in Datadog
    DD_API_KEY=...                          # required by the LLMObs writer
    DD_SITE=datadoghq.com                   # your Datadog site
    DD_ENV=production  DD_SERVICE=researchhub-backend   # optional but useful
    DD_APM_TRACING_ENABLED=false            # LLM spans only; drop APM traces
                                            # (do NOT use DD_TRACE_ENABLED=false --
                                            # that kills LLMObs spans too)

Once enabled, Bedrock Converse calls made through boto3 are auto-instrumented
as LLM spans (token usage, latency, prompt/completion). The spans created here
nest those provider calls under an ``agent`` span, with one ``tool`` span per
dispatched tool call so a full run reads as a single trace.
"""

import logging
import os
from contextlib import contextmanager

logger = logging.getLogger(__name__)

try:  # ddtrace is an optional runtime dependency for this module.
    from ddtrace.llmobs import LLMObs
except Exception:  # pragma: no cover - exercised only without ddtrace installed
    LLMObs = None

_enabled = False


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def enable_llm_observability() -> bool:
    """Enable Datadog LLM Observability if configured. Idempotent.

    Gated on ``DD_LLMOBS_ENABLED`` so local and test runs stay silent unless an
    operator opts in. Returns whether observability is now active. Any failure
    to enable is logged and swallowed -- observability must never break a run.
    """
    global _enabled
    if _enabled:
        return True
    if LLMObs is None or not _truthy(os.environ.get("DD_LLMOBS_ENABLED")):
        return False
    try:
        LLMObs.enable()
    except Exception:  # noqa: BLE001 - never let telemetry setup break startup
        logger.exception("Failed to enable Datadog LLM Observability")
        return False
    _enabled = True
    logger.info("Datadog LLM Observability enabled")
    return True


def _active() -> bool:
    return _enabled and LLMObs is not None


@contextmanager
def agent_span(name: str):
    """Wrap an agent run in an LLMObs ``agent`` span (no-op when disabled)."""
    if not _active():
        yield None
        return
    with LLMObs.agent(name=name) as span:
        yield span


@contextmanager
def tool_span(name: str):
    """Wrap a single tool dispatch in an LLMObs ``tool`` span (no-op when off)."""
    if not _active():
        yield None
        return
    with LLMObs.tool(name=name) as span:
        yield span


def annotate(span, **kwargs) -> None:
    """Annotate ``span`` with input/output/metadata/metrics; no-op when off.

    Swallows annotation errors: a telemetry hiccup must not surface as an agent
    failure.
    """
    if not _active() or span is None:
        return
    try:
        LLMObs.annotate(span=span, **kwargs)
    except Exception:  # noqa: BLE001 - telemetry must not break the run
        logger.exception("LLMObs annotate failed")
