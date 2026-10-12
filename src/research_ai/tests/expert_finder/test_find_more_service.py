"""Tests for find-more enqueue outside the HTTP boundary."""

from unittest.mock import MagicMock

from django.test import TestCase

from research_ai.models import ExpertSearch
from research_ai.services.expert_finder.find_more_service import (
    FindMoreAlreadyRunningError,
    FindMoreEnqueueError,
    FindMoreService,
)
from user.tests.helpers import create_random_authenticated_user


class FindMoreServiceTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("find_more_svc")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="CRISPR",
            status=ExpertSearch.Status.COMPLETED,
            progress=100,
            current_step="Done",
            config={"expert_count": 10, "region": "all_regions"},
            additional_context="Original notes",
        )

    def test_queue_enqueues_append_and_marks_processing(self):
        # Arrange
        enqueue = MagicMock()

        # Act
        queued = FindMoreService(enqueue=enqueue).queue(
            self.search.id,
            expert_count=15,
            additional_context="  Prefer US.  ",
        )

        # Assert
        self.search.refresh_from_db()
        self.assertEqual(queued.expert_count, 15)
        self.assertEqual(self.search.status, ExpertSearch.Status.PROCESSING)
        self.assertEqual(self.search.config["expert_count"], 15)
        self.assertEqual(self.search.additional_context, "Prefer US.")
        enqueue.assert_called_once()
        kwargs = enqueue.call_args.kwargs
        self.assertEqual(kwargs["additional_context"], "Prefer US.")
        self.assertEqual(kwargs["config"]["expert_count"], 15)

    def test_queue_raises_when_already_running(self):
        # Arrange
        self.search.status = ExpertSearch.Status.PROCESSING
        self.search.save(update_fields=["status"])

        # Act / Assert
        with self.assertRaises(FindMoreAlreadyRunningError):
            FindMoreService(enqueue=MagicMock()).queue(self.search.id, expert_count=10)

    def test_queue_restores_state_when_enqueue_fails(self):
        # Arrange
        enqueue = MagicMock(side_effect=RuntimeError("broker unavailable"))

        # Act / Assert
        with self.assertRaises(FindMoreEnqueueError):
            FindMoreService(enqueue=enqueue).queue(
                self.search.id,
                expert_count=15,
                additional_context="Prefer US.",
            )
        self.search.refresh_from_db()
        self.assertEqual(self.search.status, ExpertSearch.Status.COMPLETED)
        self.assertEqual(self.search.progress, 100)
        self.assertEqual(self.search.current_step, "Done")
        self.assertEqual(
            self.search.config, {"expert_count": 10, "region": "all_regions"}
        )
        self.assertEqual(self.search.additional_context, "Original notes")
