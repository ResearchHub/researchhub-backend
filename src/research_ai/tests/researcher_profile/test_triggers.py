"""Tests for what queues researcher-profile builds, and the Expert.profile copy."""

import importlib
from unittest.mock import patch

from django.apps import apps
from django.db import transaction
from django.test import TestCase

from research_ai import tasks
from research_ai.models import Expert, ResearcherProfile
from research_ai.services.assistant_chat.service import AssistantChatService
from research_ai.services.researcher_profile import schedule_profile_build
from user.tests.helpers import create_user
from utils.test_helpers import AWSMockTransactionTestCase

_DELAY = "research_ai.tasks.ensure_researcher_profile_task.delay"
_copy_migration = importlib.import_module(
    "research_ai.migrations.0037_copy_expert_profiles"
)


def _user(email="jane@example.edu"):
    return create_user(first_name="Jane", last_name="Doe", email=email)


class ScheduleTests(AWSMockTransactionTestCase):
    def test_queues_the_build_only_once_the_transaction_commits(self):
        # Arrange
        user = _user()
        # Act
        with patch(_DELAY) as delay, transaction.atomic():
            schedule_profile_build(user)
            queued_before_commit = delay.called
        # Assert
        self.assertFalse(queued_before_commit)
        delay.assert_called_once_with(user.pk)

    def test_rolled_back_transaction_queues_nothing(self):
        # Arrange
        user = _user()
        # Act
        with (
            patch(_DELAY) as delay,
            self.assertRaises(RuntimeError),
            transaction.atomic(),
        ):
            schedule_profile_build(user)
            raise RuntimeError("rolled back")
        # Assert
        delay.assert_not_called()

    def test_enqueue_failure_is_swallowed(self):
        # Arrange
        user = _user()
        # Act & Assert: a missed trigger must not break the caller.
        with (
            patch(_DELAY, side_effect=ConnectionError("broker down")),
            transaction.atomic(),
        ):
            schedule_profile_build(user)

    def test_assistant_chat_creation_queues_a_build(self):
        # Arrange
        user = _user()
        # Act
        with patch(_DELAY) as delay, transaction.atomic():
            AssistantChatService().create_conversation(user)
        # Assert
        delay.assert_called_once_with(user.pk)


class TaskTests(TestCase):
    def test_ensure_task_builds_for_the_user(self):
        # Arrange
        user = _user()
        # Act
        with patch.object(
            tasks.ResearcherProfileService, "ensure_for_user"
        ) as ensure_for_user:
            ensure_for_user.return_value = ResearcherProfile(id=7, status="READY")
            result = tasks.ensure_researcher_profile_task(user.pk)
        # Assert
        ensure_for_user.assert_called_once_with(user)
        self.assertEqual(result, {"profile_id": 7, "status": "READY"})

    def test_ensure_task_ignores_a_missing_user(self):
        # Act & Assert
        self.assertIsNone(tasks.ensure_researcher_profile_task(999999))

    def test_sweep_queues_each_due_user(self):
        # Arrange
        users = [_user("a@example.edu"), _user("b@example.edu")]
        for user in users:
            ResearcherProfile.objects.create(user=user)
        # Act
        with patch(_DELAY) as delay:
            result = tasks.sweep_researcher_profiles()
        # Assert
        self.assertEqual(result, {"queued": 2})
        self.assertCountEqual(
            [call.args[0] for call in delay.call_args_list],
            [user.pk for user in users],
        )

    def test_signup_linked_to_an_expert_queues_a_build(self):
        # Arrange
        user = _user()
        Expert.objects.create(email=user.email, registered_user=user)
        # Act
        with (
            patch("research_ai.tasks.link_experts_for_new_user"),
            patch(_DELAY) as delay,
        ):
            tasks.link_experts_after_signup(user.email, user.pk)
        # Assert
        delay.assert_called_once_with(user.pk)

    def test_signup_without_an_expert_queues_nothing(self):
        # Arrange
        user = _user()
        # Act
        with (
            patch("research_ai.tasks.link_experts_for_new_user"),
            patch(_DELAY) as delay,
        ):
            tasks.link_experts_after_signup(user.email, user.pk)
        # Assert
        delay.assert_not_called()


class CopyExpertProfilesMigrationTests(TestCase):
    def test_copies_built_profiles_and_links_registered_users(self):
        # Arrange
        user = _user()
        resolved = Expert.objects.create(
            email="jane@lab.edu",
            registered_user=user,
            profile={
                "schema_version": 2,
                "built_at": "2026-08-26T00:00:00+00:00",
                "resolution": {"openalex_author_id": "A1", "confidence": 0.8},
                "works": [],
                "errors": [],
            },
        )
        failed = Expert.objects.create(
            email="sam@lab.edu",
            profile={
                "schema_version": 2,
                "resolution": {"openalex_author_id": None},
                "errors": ["agent: did not submit a profile"],
            },
        )
        Expert.objects.create(email="empty@lab.edu", profile={})
        # Act
        _copy_migration.copy_expert_profiles(apps, None)
        # Assert
        self.assertEqual(ResearcherProfile.objects.count(), 2)
        copied = ResearcherProfile.objects.get(expert=resolved)
        self.assertEqual(copied.user, user)
        self.assertEqual(copied.status, ResearcherProfile.Status.READY)
        self.assertEqual(copied.openalex_author_id, "A1")
        self.assertEqual(copied.confidence, 0.8)
        self.assertEqual(copied.schema_version, 2)
        self.assertIsNotNone(copied.built_at)
        self.assertEqual(copied.data, resolved.profile)
        self.assertEqual(copied.inputs_hash, "")
        failed_copy = ResearcherProfile.objects.get(expert=failed)
        self.assertEqual(failed_copy.status, ResearcherProfile.Status.FAILED)
        self.assertEqual(failed_copy.attempts, 1)

    def test_one_user_keeps_only_one_profile(self):
        # Arrange
        user = _user()
        for email in ("a@lab.edu", "b@lab.edu"):
            Expert.objects.create(
                email=email,
                registered_user=user,
                profile={"resolution": {"openalex_author_id": "A1"}},
            )
        # Act
        _copy_migration.copy_expert_profiles(apps, None)
        # Assert
        self.assertEqual(ResearcherProfile.objects.filter(user=user).count(), 1)
        self.assertEqual(ResearcherProfile.objects.count(), 2)

    def test_rerun_does_not_duplicate(self):
        # Arrange
        Expert.objects.create(
            email="a@lab.edu", profile={"resolution": {"openalex_author_id": "A1"}}
        )
        _copy_migration.copy_expert_profiles(apps, None)
        # Act
        _copy_migration.copy_expert_profiles(apps, None)
        # Assert
        self.assertEqual(ResearcherProfile.objects.count(), 1)
