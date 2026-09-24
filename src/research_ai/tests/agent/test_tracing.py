"""Tracing initializes unconditionally and cannot change agent or tool outcomes."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from research_ai.services import tracing_service
from research_ai.services.agent.tools import Tool, Toolset
from research_ai.tests.agent.test_loop import (
    FakeProvider,
    _build_agent,
    _build_text_turn,
    _build_tool_turn,
)


class AgentTracingTests(SimpleTestCase):
    def test_initialization_failure_does_not_block_startup(self):
        # Arrange
        with (
            patch.object(tracing_service, "_trace_logger", None),
            patch.object(
                tracing_service.braintrust,
                "init_logger",
                side_effect=RuntimeError("initialization failed"),
            ),
            self.assertLogs(tracing_service.logger, level="WARNING") as logs,
        ):
            # Act
            tracing_service.initialize_tracing(
                project_id="project", project_name="name"
            )

        # Assert
        self.assertIn("Braintrust initialization failed", logs.output[0])

    def test_initialization_enables_provider_tracing_for_the_selected_project(self):
        # Arrange
        with (
            patch.object(tracing_service, "_trace_logger", None),
            patch.object(tracing_service.braintrust, "init_logger") as initialize,
            patch.object(tracing_service.braintrust, "auto_instrument") as instrument,
        ):
            # Act
            tracing_service.initialize_tracing(
                project_id="project", project_name="name"
            )

            # Assert
            initialize.assert_called_once_with(
                project="name", project_id="project", async_flush=True
            )
            instrument.assert_called_once_with()

    def test_run_and_returned_tool_error_are_visible(self):
        # Arrange
        provider = FakeProvider(
            [
                _build_tool_turn("call-1", "search", {"q": "paper"}),
                _build_text_turn("No results available."),
            ]
        )
        toolset = Toolset(
            [Tool("search", "Search", {}, lambda _: {"error": "unavailable"})]
        )
        root_context, tool_context = MagicMock(), MagicMock()
        root_span = root_context.__enter__.return_value
        tool_span = tool_context.__enter__.return_value
        with (
            patch.object(tracing_service, "_trace_logger", MagicMock()),
            patch.object(
                tracing_service.braintrust,
                "start_span",
                side_effect=[root_context, tool_context],
            ) as start,
        ):
            # Act
            result = _build_agent(provider, toolset).run("Find a paper")

        # Assert
        self.assertEqual(result.final_text, "No results available.")
        self.assertEqual(start.call_args_list[0].kwargs["name"], "agent.run")
        self.assertEqual(start.call_args_list[1].kwargs["name"], "search")
        tool_span.log.assert_any_call(error="unavailable")
        root_span.log.assert_any_call(
            output=result.final_text,
            metadata={"stop_reason": "end_turn", "iterations": 2},
        )

    def test_trace_start_failure_does_not_stop_the_agent(self):
        # Arrange
        provider = FakeProvider([_build_text_turn("Done")])
        with (
            patch.object(tracing_service, "_trace_logger", MagicMock()),
            patch.object(
                tracing_service.braintrust, "start_span", side_effect=RuntimeError
            ),
            self.assertLogs(tracing_service.logger, level="WARNING"),
        ):
            # Act
            result = _build_agent(provider, Toolset()).run("Go")

        # Assert
        self.assertEqual(result.final_text, "Done")
        self.assertEqual(len(provider.calls), 1)

    def test_trace_failures_preserve_the_original_cancellation(self):
        # Arrange
        context = MagicMock()
        context.__enter__.return_value.log.side_effect = RuntimeError("log failed")
        context.__exit__.side_effect = RuntimeError("finish failed")
        cancellation = InterruptedError("cancelled")
        with (
            patch.object(tracing_service, "_trace_logger", MagicMock()),
            patch.object(
                tracing_service.braintrust, "start_span", return_value=context
            ),
            self.assertLogs(tracing_service.logger, level="WARNING"),
            self.assertRaises(InterruptedError) as raised,
            tracing_service.trace_operation("run", span_type="task"),
        ):
            # Act
            raise cancellation

        # Assert
        self.assertIs(raised.exception, cancellation)

    def test_worker_shutdown_flushes_buffered_traces(self):
        # Arrange
        with patch.object(tracing_service, "_trace_logger") as trace_logger:
            # Act
            tracing_service.flush_tracing(pid=123, exitcode=0)

            # Assert
            trace_logger.flush.assert_called_once_with()
