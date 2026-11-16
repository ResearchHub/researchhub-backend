"""Tracing initializes unconditionally and cannot change agent or tool outcomes."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from research_ai.services import tracing_service
from research_ai.services.agent.errors import ProviderError
from research_ai.services.agent.run_metrics import RunToolMetrics
from research_ai.services.agent.tools import Tool, Toolset
from research_ai.tests.agent.test_loop import (
    FakeProvider,
    RecordingRecorder,
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
        metadata = next(
            call.kwargs["metadata"]
            for call in root_span.log.call_args_list
            if "tool_calls" in call.kwargs.get("metadata", {})
        )
        self.assertEqual(metadata["tool_calls"], 1)
        self.assertEqual(metadata["tool_errors"], 1)
        self.assertEqual(metadata["note_edit_outcome"], "not_attempted")

    def test_failed_save_is_visible_even_when_the_agent_finishes_normally(self):
        # Arrange
        provider = FakeProvider(
            [
                _build_tool_turn("edit-1", "edit_note", {"note_id": 123}),
                _build_text_turn("I could not save your document."),
            ]
        )
        tools = Toolset(
            [Tool("edit_note", "Edit", {}, lambda _: {"error": "not accessible"})]
        )
        root_context, tool_context = MagicMock(), MagicMock()
        root_span = root_context.__enter__.return_value
        recorder = RecordingRecorder()
        recorder.execution = SimpleNamespace(
            id=12,
            conversation_id=34,
            conversation=SimpleNamespace(user_id=56, workflow="notebook_chat"),
        )
        with (
            patch.object(tracing_service, "_trace_logger", MagicMock()),
            patch.object(
                tracing_service.braintrust,
                "start_span",
                side_effect=[root_context, tool_context],
            ) as start,
        ):
            # Act
            result = _build_agent(provider, tools, recorder=recorder).run("Save it")

        # Assert
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertEqual(start.call_args_list[0].kwargs["metadata"]["user_id"], 56)
        self.assertEqual(
            start.call_args_list[0].kwargs["metadata"]["workflow"], "notebook_chat"
        )
        metadata = next(
            call.kwargs["metadata"]
            for call in root_span.log.call_args_list
            if "note_edit_outcome" in call.kwargs.get("metadata", {})
        )
        self.assertEqual(metadata["note_edit_outcome"], "failed")
        self.assertEqual(metadata["note_edit_attempts"], 1)
        self.assertEqual(metadata["note_edits_saved"], 0)

    def test_note_edit_metrics_distinguish_recovery_from_saving_another_note(self):
        # Arrange
        metrics = RunToolMetrics()

        # Act
        metrics.observe("edit_note", {"note_id": 1}, {"error": "stale version"})
        metrics.observe("edit_note", {"note_id": 2}, {"saved": True})

        # Assert
        self.assertEqual(metrics.metadata()["note_edit_outcome"], "partially_saved")
        self.assertEqual(metrics.metadata()["note_edit_recoveries"], 0)

        # Act: the original note is saved on retry, including a string id.
        metrics.observe("edit_note", {"note_id": "1"}, {"saved": True})

        # Assert
        self.assertEqual(metrics.metadata()["note_edit_outcome"], "saved")
        self.assertEqual(metrics.metadata()["note_edit_recoveries"], 1)
        self.assertEqual(metrics.metadata()["note_edits_saved"], 2)
        self.assertEqual(metrics.metadata()["unresolved_note_edit_errors"], 0)

    def test_save_metrics_reset_on_each_turn_and_require_confirmed_save(self):
        # Arrange
        provider = FakeProvider(
            [
                _build_tool_turn("edit-1", "edit_note", {"note_id": 1}),
                _build_text_turn("Finished"),
                _build_text_turn("Hello"),
            ]
        )
        agent = _build_agent(
            provider,
            Toolset([Tool("edit_note", "Edit", {}, lambda _: {"saved": False})]),
        )

        # Act
        first = agent.run("Save it")
        first_metrics = agent._run_tool_metrics.metadata()
        agent.continue_conversation(first.messages, "Hello")

        # Assert
        self.assertEqual(first_metrics["note_edit_outcome"], "failed")
        self.assertEqual(
            agent._run_tool_metrics.metadata()["note_edit_outcome"], "not_attempted"
        )
        self.assertEqual(agent._run_tool_metrics.metadata()["tool_calls"], 0)

    def test_save_metrics_survive_a_later_provider_failure(self):
        # Arrange
        provider = FakeProvider(
            [
                _build_tool_turn("edit-1", "edit_note", {"note_id": 1}),
            ]
        )
        tools = Toolset([Tool("edit_note", "Edit", {}, lambda _: {"saved": True})])
        root_context, tool_context = MagicMock(), MagicMock()
        root_span = root_context.__enter__.return_value
        with (
            patch.object(tracing_service, "_trace_logger", MagicMock()),
            patch.object(
                tracing_service.braintrust,
                "start_span",
                side_effect=[root_context, tool_context],
            ),
            self.assertRaises(ProviderError),
        ):
            # Act: the fake provider has no second response, after the save.
            _build_agent(provider, tools).run("Save it")

        # Assert: the save is observable even without a final chat response.
        metadata = next(
            call.kwargs["metadata"]
            for call in root_span.log.call_args_list
            if "note_edit_outcome" in call.kwargs.get("metadata", {})
        )
        self.assertEqual(metadata["note_edit_outcome"], "saved")
        self.assertEqual(metadata["note_edits_saved"], 1)

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
