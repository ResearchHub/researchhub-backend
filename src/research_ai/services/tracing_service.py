"""Always initialize Braintrust tracing without disrupting agent execution."""

import logging
from contextlib import contextmanager

import braintrust

logger = logging.getLogger(__name__)
_trace_logger = None


def initialize_tracing(*, project_id: str, project_name: str) -> None:
    global _trace_logger
    try:
        _trace_logger = braintrust.init_logger(
            project=project_name, project_id=project_id, async_flush=True
        )
        # Includes OpenAI (OpenRouter), Anthropic (AnthropicAWS), and Bedrock.
        braintrust.auto_instrument()
    except Exception:  # noqa: BLE001 - preserve application startup
        logger.warning("Braintrust initialization failed", exc_info=True)


def flush_tracing(**kwargs) -> None:
    """Send buffered observations when a Celery worker exits gracefully."""
    if _trace_logger is not None:
        try:
            _trace_logger.flush()
        except Exception:  # noqa: BLE001 - preserve worker shutdown
            logger.warning("Braintrust flush failed", exc_info=True)


def log_trace(span, **fields) -> None:
    if span is not None:
        try:
            span.log(**fields)
        except Exception:  # noqa: BLE001 - preserve the observed operation
            logger.warning("Braintrust observation failed", exc_info=True)


@contextmanager
def trace_operation(name: str, *, span_type: str, **fields):
    """Nest an operation, isolating SDK errors from the operation's own errors."""
    context = None
    span = None
    if _trace_logger is not None:
        try:
            context = braintrust.start_span(name=name, type=span_type, **fields)
            span = context.__enter__()
        except Exception:  # noqa: BLE001 - run even if tracing cannot start
            context = None
            logger.warning("Braintrust span start failed", exc_info=True)
    try:
        yield span
    except BaseException as error:
        log_trace(span, error=f"{type(error).__name__}: {error}")
        raise
    finally:
        if context is not None:
            try:
                context.__exit__(None, None, None)
            except Exception:  # noqa: BLE001 - preserve the result or exception
                logger.warning("Braintrust span finish failed", exc_info=True)
