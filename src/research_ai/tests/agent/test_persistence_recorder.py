"""Execution recorder, lifecycle, and trace persistence coverage."""

import json
from unittest.mock import patch

from django.db import IntegrityError, transaction

from research_ai.models import (
    AgentContextMessage,
    AgentConversation,
    AgentConversationMessage,
    AgentExecution,
    AgentExecutionMessage,
)
from research_ai.services.agent.loop import AgentResult
from research_ai.services.agent.tools import MAX_TOOL_RESULT_BYTES, Tool
from research_ai.services.agent.types import (
    StopReason,
    TurnUsage,
    deserialize_messages,
)
from research_ai.services.agent_persistence import AgentExecutionService
from research_ai.services.agent_persistence.content import (
    MAX_CONTEXT_MESSAGE_BYTES,
    MAX_TRACE_MESSAGE_BYTES,
)
from research_ai.tests.agent.persistence_test_helpers import (
    AgentPersistenceTestCase,
    FakeProvider,
    agent,
    text_turn,
    tool_turn,
)


class AgentRecorderPersistenceTests(AgentPersistenceTestCase):
    def test_successful_tool_run_persists_trace_metrics_and_details(self):
        # Arrange
        first_usage = TurnUsage(10, 4, 7, 3)
        second_usage = TurnUsage(20, 5, 14, 2)
        provider = FakeProvider(
            [
                tool_turn(
                    "call-1",
                    "lookup",
                    {"query": "folding"},
                    usage=first_usage,
                    latency_ms=31,
                ),
                text_turn("Finished", usage=second_usage, latency_ms=47),
            ]
        )
        recorder = self.recorder(
            initial_prompt_provenance=AgentExecutionMessage.Provenance.HUMAN
        )
        tool = Tool(
            "lookup",
            "lookup",
            {"type": "object"},
            lambda _args: {"papers": ["A"]},
        )

        # Act
        result = agent(provider, recorder, [tool]).run("Find papers")

        # Assert
        execution = AgentExecution.objects.get(id=recorder.execution.id)
        self.assertEqual(execution.status, AgentExecution.Status.SUCCEEDED)
        self.assertEqual(execution.iterations, 2)
        self.assertEqual(execution.input_tokens, 30)
        self.assertEqual(execution.output_tokens, 9)
        self.assertEqual(execution.cache_read_tokens, 21)
        self.assertEqual(execution.cache_write_tokens, 5)
        self.assertEqual(execution.total_latency_ms, 78)
        self.assertEqual(execution.stop_reason, StopReason.END_TURN)
        self.assertIsNotNone(execution.duration_ms)
        self.assertEqual(execution.final_output, {"text": "Finished"})
        self.assertEqual(result.final_text, "Finished")

        trace = list(execution.messages.order_by("execution_sequence"))
        self.assertEqual([row.execution_sequence for row in trace], [1, 2, 3, 4])
        self.assertEqual(
            [row.provenance for row in trace],
            [
                AgentExecutionMessage.Provenance.HUMAN,
                AgentExecutionMessage.Provenance.MODEL,
                AgentExecutionMessage.Provenance.TOOL,
                AgentExecutionMessage.Provenance.MODEL,
            ],
        )
        self.assertEqual(trace[1].content[1]["input"], {"query": "folding"})
        self.assertEqual(trace[2].content[0]["content"], {"papers": ["A"]})

    def test_failed_and_interrupted_runs_keep_partial_history(self):
        # Arrange
        failed_recorder = self.recorder()
        provider = FakeProvider(
            [
                tool_turn("call-1", "lookup", {}),
                ValueError("provider socket closed"),
            ]
        )
        tool = Tool("lookup", "lookup", {"type": "object"}, lambda _args: {})

        # Act / Assert
        with self.assertRaisesRegex(Exception, "provider socket closed"):
            agent(provider, failed_recorder, [tool]).run("start")
        failed = AgentExecution.objects.get(id=failed_recorder.execution.id)
        self.assertEqual(failed.status, AgentExecution.Status.FAILED)
        self.assertEqual(failed.error_type, "ProviderError")
        self.assertEqual(failed.messages.count(), 3)
        self.assertEqual(failed.iterations, 1)

        interrupted_recorder = self.recorder()
        with self.assertRaises(InterruptedError):
            agent(
                FakeProvider([InterruptedError("worker stopped")]),
                interrupted_recorder,
            ).run("start")
        interrupted = AgentExecution.objects.get(id=interrupted_recorder.execution.id)
        self.assertEqual(interrupted.status, AgentExecution.Status.INTERRUPTED)
        self.assertEqual(interrupted.messages.count(), 1)
        self.assertEqual(interrupted.error_type, "InterruptedError")

    def test_tool_errors_are_persisted_as_correlated_results(self):
        # Arrange
        recorder = self.recorder()
        provider = FakeProvider(
            [tool_turn("broken-1", "broken", {}), text_turn("recovered")]
        )

        def fail(_args):
            raise RuntimeError("tool unavailable")

        tool = Tool("broken", "broken", {"type": "object"}, fail)

        # Act
        agent(provider, recorder, [tool]).run("try it")

        # Assert
        result_block = recorder.execution.messages.get(execution_sequence=3).content[0]
        self.assertEqual(result_block["tool_use_id"], "broken-1")
        self.assertTrue(result_block["is_error"])
        self.assertEqual(result_block["content"], {"error": "tool unavailable"})

    def test_unexpected_setup_exception_marks_execution_failed(self):
        # Arrange
        recorder = self.recorder()
        provider = FakeProvider([], render_error=RuntimeError("bad tool schema"))

        # Act / Assert
        with self.assertRaisesRegex(RuntimeError, "bad tool schema"):
            agent(provider, recorder).run("hello")
        execution = AgentExecution.objects.get(id=recorder.execution.id)
        self.assertEqual(execution.status, AgentExecution.Status.FAILED)
        self.assertEqual(execution.error_type, "RuntimeError")
        self.assertEqual(execution.messages.count(), 1)

    def test_required_context_failure_marks_execution_failed(self):
        # Arrange
        recorder = self.recorder()
        running_agent = agent(FakeProvider([text_turn("unreachable")]), recorder)

        # Act / Assert
        with (
            patch.object(
                AgentContextMessage.objects,
                "create",
                side_effect=IntegrityError("context write failed"),
            ),
            self.assertRaisesRegex(IntegrityError, "context write failed"),
        ):
            running_agent.run("hello")

        execution = AgentExecution.objects.get(id=recorder.execution.id)
        self.assertEqual(execution.status, AgentExecution.Status.FAILED)
        self.assertEqual(execution.error_type, "IntegrityError")
        self.assertEqual(execution.context_messages.count(), 0)
        self.assertEqual(execution.messages.count(), 0)

    def test_terminal_callback_does_not_overwrite_cancelled_execution(self):
        # Arrange
        recorder = self.recorder(publish_assistant_message=True)
        AgentExecution.objects.filter(id=recorder.execution.id).update(
            status=AgentExecution.Status.CANCELLED
        )
        result = AgentResult(
            messages=[],
            final_text="late answer",
            stop_reason=StopReason.END_TURN,
            iterations=1,
        )

        # Act
        recorder.on_run_finished(result)

        # Assert
        execution = AgentExecution.objects.get(id=recorder.execution.id)
        self.assertEqual(execution.status, AgentExecution.Status.CANCELLED)
        self.assertEqual(execution.final_output, {})
        self.assertFalse(hasattr(execution, "generated_chat_message"))
        self.assertTrue(recorder.terminal_observed)

    def test_oversized_tool_result_never_reaches_the_durable_rows(self):
        # Arrange: the dispatch cap turns a flooding tool into an error the
        # model can act on, which is why persistence never has to compact a
        # message to fit its row.
        recorder = self.recorder()
        provider = FakeProvider(
            [
                tool_turn("large", "large_tool", {"query": "everything"}),
                text_turn("narrowing the query"),
            ]
        )
        tool = Tool(
            "large_tool",
            "large",
            {"type": "object"},
            lambda _args: {"result": "x" * (MAX_TOOL_RESULT_BYTES * 2)},
        )

        # Act
        agent(provider, recorder, [tool]).run("go")

        # Assert
        context_rows = list(recorder.execution.context_messages.order_by("sequence"))
        self.assertFalse(any(row.is_compacted for row in context_rows))
        result_block = context_rows[2].content[0]
        self.assertEqual(result_block["tool_use_id"], "large")
        self.assertTrue(result_block["is_error"])
        self.assertIn("over the", result_block["content"]["error"])
        for row in context_rows:
            self.assertLessEqual(
                len(json.dumps(row.content).encode()), MAX_CONTEXT_MESSAGE_BYTES
            )
            deserialize_messages([{"role": row.role, "content": row.content}])

    def test_chat_publication_keeps_the_untruncated_response(self):
        # Arrange: chat content is unbounded, so the answer the user reads must
        # not inherit the truncation that bounds the execution row.
        long_answer = "x" * (MAX_TRACE_MESSAGE_BYTES * 2)
        recorder = self.recorder(publish_assistant_message=True)
        provider = FakeProvider([text_turn(long_answer)])

        # Act
        agent(provider, recorder).run("go")

        # Assert
        execution = AgentExecution.objects.get(id=recorder.execution.id)
        self.assertTrue(execution.final_output["_truncated"])
        self.assertLess(len(execution.final_output["text"]), len(long_answer))
        published = AgentConversationMessage.objects.get(
            generated_by_execution_id=execution.id
        )
        self.assertEqual(published.content, long_answer)

    def test_provider_state_round_trips_through_context_messages(self):
        # Arrange: Claude's container id is request-level state the next turn
        # must replay, so it has to survive the recorder, not just the serializer.
        container = {
            "anthropic": {
                "container": {
                    "id": "container_123",
                    "expires_at": "2026-07-29T21:30:00Z",
                }
            }
        }
        recorder = self.recorder()
        provider = FakeProvider([text_turn("Done", provider_state=container)])

        # Act
        agent(provider, recorder).run("go")

        # Assert
        assistant_row = recorder.execution.context_messages.get(role="assistant")
        self.assertEqual(assistant_row.provider_state, container)
        restored = deserialize_messages(
            [
                {
                    "role": assistant_row.role,
                    "content": assistant_row.content,
                    "provider_state": assistant_row.provider_state,
                }
            ]
        )[0]
        self.assertEqual(restored.provider_state, container)

        # A turn without provider state stays empty rather than inheriting.
        user_row = recorder.execution.context_messages.get(role="user")
        self.assertEqual(user_row.provider_state, {})

    def test_headless_workflow_has_no_artificial_chat_messages(self):
        # Arrange
        workflow = AgentConversation.objects.create(workflow="headless")
        recorder = AgentExecutionService().start(workflow)

        # Act
        agent(FakeProvider([text_turn("internal result")]), recorder).run(
            "backend prompt"
        )

        # Assert
        self.assertEqual(workflow.chat_messages.count(), 0)
        self.assertEqual(
            recorder.execution.messages.first().provenance,
            AgentExecutionMessage.Provenance.BACKEND,
        )

    def test_optional_trace_failure_does_not_break_surrounding_transaction(self):
        # Arrange
        recorder = self.recorder()
        running_agent = agent(FakeProvider([text_turn("still succeeds")]), recorder)

        # Act
        with transaction.atomic():
            with patch.object(
                AgentExecutionMessage.objects,
                "create",
                side_effect=IntegrityError("trace write failed"),
            ):
                result = running_agent.run("hello")
            AgentConversation.objects.create()

        # Assert
        self.assertEqual(result.final_text, "still succeeds")
        self.assertEqual(
            AgentExecution.objects.get(id=recorder.execution.id).status,
            AgentExecution.Status.SUCCEEDED,
        )
        self.assertEqual(recorder.execution.context_messages.count(), 2)
        self.assertEqual(AgentExecutionMessage.objects.count(), 0)
        self.assertEqual(AgentContextMessage.objects.count(), 2)
