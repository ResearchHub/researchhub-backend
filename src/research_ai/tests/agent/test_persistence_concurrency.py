"""Concurrent sequence allocation coverage for agent persistence."""

import threading

from django.db import close_old_connections
from django.test import TransactionTestCase

from research_ai.models import AgentConversation, AgentExecution, AgentExecutionMessage
from research_ai.services.agent.types import Message, TextBlock
from research_ai.services.agent_persistence import (
    AgentExecutionService,
    DatabaseAgentRecorder,
)


class AgentSequenceConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_concurrent_trace_writes_allocate_unique_ordered_sequences(self):
        # Arrange
        conversation = AgentConversation.objects.create()
        execution = AgentExecutionService().start(conversation).execution
        barrier = threading.Barrier(4)
        errors = []

        def record(index):
            close_old_connections()
            try:
                local_execution = AgentExecution.objects.get(id=execution.id)
                barrier.wait()
                DatabaseAgentRecorder(local_execution).record_message(
                    Message(role="user", content=[TextBlock(text=str(index))])
                )
            except Exception as exc:  # noqa: BLE001 - surfaced in main test thread
                errors.append(exc)
            finally:
                close_old_connections()

        # Act
        threads = [threading.Thread(target=record, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        # Assert
        self.assertFalse(errors)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        rows = list(
            AgentExecutionMessage.objects.filter(execution=execution).order_by(
                "sequence"
            )
        )
        self.assertEqual([row.sequence for row in rows], [1, 2, 3, 4])
        self.assertEqual(sorted(row.execution_sequence for row in rows), [1, 2, 3, 4])
