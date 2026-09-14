"""The worker heartbeat that keeps a budget lease alive independent of the loop."""

from datetime import timedelta
from threading import Event
from unittest.mock import Mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from research_ai.models import AgentConversation, AgentExecution
from research_ai.services.usage_budget import (
    AgentLoopBudgetRecorder,
    ReservationHeartbeat,
)
from user.tests.helpers import create_random_authenticated_user


class _Target:
    """The one attribute the heartbeat reads off a reservation row."""

    def __init__(self, id, expires_at):
        self.id = id
        self.usage_reservation_expires_at = expires_at


class ReservationHeartbeatThreadTests(SimpleTestCase):
    def test_beats_from_its_own_thread_until_stopped(self):
        # Arrange
        beaten = Event()

        def renew(target, *, now):
            beaten.set()
            return True

        heartbeat = ReservationHeartbeat(
            [_Target(1, timezone.now())],
            interval=timedelta(milliseconds=10),
            renew=Mock(side_effect=renew),
        )

        # Act
        with heartbeat:
            first_beat = beaten.wait(timeout=5)

        # Assert
        self.assertTrue(first_beat)
        self.assertFalse(heartbeat.lost)

    def test_rows_without_a_reservation_take_no_part(self):
        # Arrange
        renew = Mock(return_value=True)
        heartbeat = ReservationHeartbeat([_Target(1, None), None], renew=renew)

        # Act
        with heartbeat:
            heartbeat.beat()

        # Assert
        self.assertEqual(heartbeat.targets, ())
        renew.assert_not_called()

    def test_a_beat_that_finds_no_live_lease_marks_it_lost(self):
        # Arrange
        heartbeat = ReservationHeartbeat(
            [_Target(1, timezone.now())], renew=Mock(return_value=False)
        )

        # Act
        alive = heartbeat.beat()

        # Assert
        self.assertFalse(alive)
        self.assertTrue(heartbeat.lost)

    def test_a_failing_beat_is_tolerated(self):
        # Arrange: the lease outlives several missed beats, so a database hiccup
        # is retried on the next tick rather than treated as a lost lease.
        heartbeat = ReservationHeartbeat(
            [_Target(1, timezone.now())],
            renew=Mock(side_effect=RuntimeError("database hiccup")),
        )

        # Act
        alive = heartbeat.beat()

        # Assert
        self.assertTrue(alive)
        self.assertFalse(heartbeat.lost)


class ReservationHeartbeatLeaseTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("heartbeat")

    def _execution(self, *, status, expires_at):
        conversation = AgentConversation.objects.create(
            user=self.user, workflow="notebook_chat"
        )
        return AgentExecution.objects.create(
            conversation=conversation,
            status=status,
            attempt=1,
            usage_reservation_expires_at=expires_at,
        )

    def test_a_beat_renews_a_running_workers_lease(self):
        # Arrange
        old_expiry = timezone.now() + timedelta(minutes=1)
        execution = self._execution(
            status=AgentExecution.Status.RUNNING, expires_at=old_expiry
        )

        # Act
        alive = ReservationHeartbeat((execution,)).beat()

        # Assert
        execution.refresh_from_db()
        self.assertTrue(alive)
        self.assertGreater(execution.usage_reservation_expires_at, old_expiry)

    def test_a_beat_keeps_a_cancelled_in_flight_call_reserved(self):
        # Arrange: cancellation landed, but the worker -- and possibly its paid
        # provider call -- is demonstrably still alive.
        old_expiry = timezone.now() + timedelta(minutes=1)
        execution = self._execution(
            status=AgentExecution.Status.CANCELLED, expires_at=old_expiry
        )

        # Act
        ReservationHeartbeat((execution,)).beat()

        # Assert
        execution.refresh_from_db()
        self.assertGreater(execution.usage_reservation_expires_at, old_expiry)

    def test_a_late_beat_cannot_revive_a_lapsed_lease(self):
        # Arrange: admission may already have handed the slot to another job.
        old_expiry = timezone.now() - timedelta(seconds=1)
        execution = self._execution(
            status=AgentExecution.Status.CANCELLED, expires_at=old_expiry
        )
        heartbeat = ReservationHeartbeat((execution,))

        # Act
        alive = heartbeat.beat()

        # Assert
        execution.refresh_from_db()
        self.assertFalse(alive)
        self.assertTrue(heartbeat.lost)
        self.assertEqual(execution.usage_reservation_expires_at, old_expiry)

    def test_a_straggling_beat_leaves_a_released_lease_released(self):
        # Arrange: the worker unwound and cleared the lease before its
        # heartbeat thread observed the stop.
        execution = self._execution(
            status=AgentExecution.Status.RUNNING,
            expires_at=timezone.now() + timedelta(minutes=1),
        )
        heartbeat = ReservationHeartbeat((execution,))
        AgentExecution.objects.filter(id=execution.id).update(
            usage_reservation_expires_at=None
        )

        # Act
        heartbeat.beat()

        # Assert
        execution.refresh_from_db()
        self.assertIsNone(execution.usage_reservation_expires_at)


class AgentLoopBudgetRecorderHeartbeatTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("heartbeat-recorder")
        conversation = AgentConversation.objects.create(
            user=self.user, workflow="notebook_chat"
        )
        self.execution = AgentExecution.objects.create(
            conversation=conversation,
            status=AgentExecution.Status.RUNNING,
            attempt=1,
            usage_reservation_expires_at=timezone.now() + timedelta(minutes=1),
        )

    def _recorder(self, heartbeat):
        return AgentLoopBudgetRecorder(
            user=self.user,
            feature="notebook_chat",
            provider="openrouter",
            model_id="deepseek/deepseek-v4-pro-0813",
            execution=self.execution,
            heartbeat=heartbeat,
        )

    def test_a_lost_lease_stops_the_run_before_its_next_model_call(self):
        # Arrange: the process lost the database for longer than the lease.
        heartbeat = ReservationHeartbeat((self.execution,))
        AgentExecution.objects.filter(id=self.execution.id).update(
            usage_reservation_expires_at=timezone.now() - timedelta(seconds=1)
        )
        heartbeat.beat()
        recorder = self._recorder(heartbeat)

        # Act / Assert
        self.assertFalse(recorder.is_active())
        with self.assertRaises(InterruptedError):
            recorder.before_model_call()

    def test_a_live_heartbeat_lets_the_run_spend(self):
        # Arrange
        heartbeat = ReservationHeartbeat((self.execution,))
        heartbeat.beat()
        recorder = self._recorder(heartbeat)

        # Act / Assert
        self.assertTrue(recorder.is_active())
        recorder.before_model_call()
