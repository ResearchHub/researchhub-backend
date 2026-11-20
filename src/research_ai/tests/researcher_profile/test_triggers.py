"""Tests for what queues researcher-profile builds."""

from io import StringIO
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.db import transaction
from django.test import TestCase

from research_ai import tasks
from research_ai.models import AgentConversation, Expert, ResearcherProfile
from research_ai.services.assistant_chat.service import AssistantChatService
from research_ai.services.notebook_chat import ASSISTANT_WORKFLOW
from research_ai.services.notebook_chat import WORKFLOW as NOTEBOOK_WORKFLOW
from research_ai.services.researcher_profile import schedule_profile_build
from user.tests.helpers import create_user
from utils.test_helpers import AWSMockTransactionTestCase

_DELAY = "research_ai.tasks.ensure_researcher_profile_task.delay"


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

        def schedule_then_fail():
            with transaction.atomic():
                schedule_profile_build(user)
                raise RuntimeError("rolled back")

        # Act
        with patch(_DELAY) as delay, self.assertRaises(RuntimeError):
            schedule_then_fail()
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


class ScheduleGuardTests(TestCase):
    def test_no_user_queues_nothing(self):
        # Act
        with patch(_DELAY) as delay, self.captureOnCommitCallbacks(execute=True):
            schedule_profile_build(None)
        # Assert
        delay.assert_not_called()


class BackfillCommandTests(TestCase):
    def setUp(self):
        self.users = [_user("a@example.edu"), _user("b@example.edu")]
        for user in self.users:
            AgentConversation.objects.create(user=user, workflow=NOTEBOOK_WORKFLOW)
        # A second chat for the same user is still one build.
        AgentConversation.objects.create(
            user=self.users[0], workflow=ASSISTANT_WORKFLOW
        )
        AgentConversation.objects.create(
            user=_user("gone@example.edu"), workflow=NOTEBOOK_WORKFLOW, is_removed=True
        )
        AgentConversation.objects.create(
            user=_user("other@example.edu"), workflow="proposal_draft"
        )

    def test_queues_each_chat_user_once(self):
        # Act
        with patch(_DELAY) as delay:
            call_command("backfill_researcher_profiles", stdout=StringIO())
        # Assert
        self.assertCountEqual(
            [call.args[0] for call in delay.call_args_list],
            [user.pk for user in self.users],
        )

    def test_users_with_a_profile_row_are_skipped(self):
        # Arrange
        ResearcherProfile.objects.create(user=self.users[0])
        # Act
        with patch(_DELAY) as delay:
            call_command("backfill_researcher_profiles", stdout=StringIO())
        # Assert
        self.assertEqual(
            [call.args[0] for call in delay.call_args_list], [self.users[1].pk]
        )

    def test_dry_run_queues_nothing(self):
        # Arrange
        out = StringIO()
        # Act
        with patch(_DELAY) as delay:
            call_command("backfill_researcher_profiles", "--dry-run", stdout=out)
        # Assert
        delay.assert_not_called()
        self.assertIn("Would queue 2", out.getvalue())

    def test_limit_caps_the_queue(self):
        # Act
        with patch(_DELAY) as delay:
            call_command(
                "backfill_researcher_profiles", "--limit", "1", stdout=StringIO()
            )
        # Assert: users are taken in id order.
        self.assertEqual(
            [call.args[0] for call in delay.call_args_list], [self.users[0].pk]
        )

    def test_user_ids_override_the_chat_users(self):
        # Act
        with patch(_DELAY) as delay:
            call_command(
                "backfill_researcher_profiles", "--user-ids", "7,8", stdout=StringIO()
            )
        # Assert
        self.assertEqual([call.args[0] for call in delay.call_args_list], [7, 8])

    def test_limit_also_caps_explicit_user_ids(self):
        # Act
        with patch(_DELAY) as delay:
            call_command(
                "backfill_researcher_profiles",
                "--user-ids",
                "7,8,9",
                "--limit",
                "2",
                stdout=StringIO(),
            )
        # Assert
        self.assertEqual([call.args[0] for call in delay.call_args_list], [7, 8])

    def test_bad_user_ids_are_rejected(self):
        # Act & Assert
        with self.assertRaises(CommandError):
            call_command("backfill_researcher_profiles", "--user-ids", "a,b")


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
