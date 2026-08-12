import json
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, TransactionTestCase

from note.tests.helpers import create_note
from research_ai.models import (
    AgentConversation,
    AgentExecution,
    NoteAgentConversation,
)
from research_ai.services.agent.types import StopReason
from research_ai.services.agent_persistence import (
    AgentConversationBusyError,
    DatabaseAgentRecorder,
)
from research_ai.services.notebook_chat import WORKFLOW, NotebookChatService
from research_ai.services.notebook_chat.config import NotebookChatConfig
from research_ai.services.notebook_chat.events import (
    TURN_CANCELLED,
    TURN_FAILED,
    TURN_FINISHED,
    TURN_PROGRESS,
    TURN_QUEUED,
    ConversationEventPublisher,
)
from research_ai.services.notebook_chat.service import TITLE_MAX_CHARS
from research_ai.tests.agent.persistence_test_helpers import (
    FakeProvider,
    text_turn,
    tool_turn,
)
from research_ai.tests.notebook_chat.test_notebook_chat_events import FakeChannelLayer
from researchhub_access_group.constants import ADMIN
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument

EDITED_DOC = {
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Edited by the assistant"}],
        }
    ],
}


def _make_service(provider=None, **kwargs):
    return NotebookChatService(
        provider=provider,
        oa_client=Mock(),
        web_search_client=Mock(configured=False),
        **kwargs,
    )


class CapturingProvider(FakeProvider):
    """Records the ``max_tokens`` each ``complete`` call was given."""

    def __init__(self, turns):
        super().__init__(turns)
        self.max_tokens_seen = []

    def complete(self, **kwargs):
        self.max_tokens_seen.append(kwargs["max_tokens"])
        return super().complete(**kwargs)


class NotebookChatServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.note, self.content = create_note(self.user, organization=None)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note.unified_document.id,
            user=self.user,
        )
        self.service = _make_service()
        self.conversation = self.service.create_conversation(self.note, self.user)

    def _submit(self, text="Please add a summary.", conversation=None):
        conversation = self.conversation if conversation is None else conversation
        with (
            patch("research_ai.tasks.run_notebook_chat_turn_task.delay") as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            execution = self.service.submit_message(self.note, conversation, text)
        return execution, delay

    def test_submit_message_prepares_turn_and_schedules_task(self):
        # Act
        execution, delay = self._submit()

        # Assert
        conversation = execution.conversation
        self.assertEqual(conversation.workflow, WORKFLOW)
        self.assertEqual(conversation.user, self.user)
        self.assertTrue(conversation.note_links.filter(note=self.note).exists())
        # Queued for the worker to claim; RUNNING only once a worker owns it.
        self.assertEqual(execution.status, AgentExecution.Status.PENDING)
        self.assertIn(str(self.note.id), execution.system_prompt)
        self.assertIn(self.note.title, execution.system_prompt)
        self.assertEqual(execution.configuration["note_id"], self.note.id)
        self.assertEqual(execution.trigger_message.content, "Please add a summary.")
        delay.assert_called_once_with(execution.id)

    def test_second_message_continues_the_same_conversation(self):
        # Arrange
        first, _delay = self._submit()
        first.status = AgentExecution.Status.SUCCEEDED
        first.save(update_fields=["status"])

        # Act
        second, _delay = self._submit("Another request")

        # Assert
        self.assertEqual(second.conversation_id, first.conversation_id)
        self.assertEqual(second.context_parent_id, first.id)

    def test_submit_message_rejects_empty_and_oversized_messages(self):
        # Arrange
        service = _make_service(config=NotebookChatConfig(max_message_chars=10))

        # Act & Assert
        with self.assertRaises(ValueError):
            service.submit_message(self.note, self.conversation, "   ")
        with self.assertRaises(ValueError):
            service.submit_message(self.note, self.conversation, "x" * 11)

    def test_create_conversation_makes_a_new_chat_each_time(self):
        # Act
        second = self.service.create_conversation(self.note, self.user)

        # Assert: both chats coexist on the note for the same user.
        self.assertNotEqual(second.id, self.conversation.id)
        self.assertEqual(
            AgentConversation.objects.filter(
                user=self.user, workflow=WORKFLOW, note_links__note=self.note
            ).count(),
            2,
        )

    def test_submit_message_while_turn_is_running_raises_busy(self):
        # Arrange
        self._submit()

        # Act & Assert
        with self.assertRaises(AgentConversationBusyError):
            self.service.submit_message(self.note, self.conversation, "again")

    def test_busy_chat_does_not_block_the_users_other_chats(self):
        # Arrange: a turn is pending on the first chat.
        self._submit()
        second = self.service.create_conversation(self.note, self.user)

        # Act
        execution, _delay = self._submit("Different thread", conversation=second)

        # Assert: each chat serializes its own turns independently.
        self.assertEqual(execution.conversation_id, second.id)
        self.assertEqual(execution.status, AgentExecution.Status.PENDING)

    def test_run_turn_edits_note_and_publishes_reply(self):
        # Arrange
        execution, _delay = self._submit("Replace the note body.")
        provider = FakeProvider(
            [
                tool_turn("t1", "read_note", {"note_id": self.note.id}),
                tool_turn(
                    "t2",
                    "edit_note",
                    {
                        "note_id": self.note.id,
                        "expected_version_id": self.content.id,
                        "content": EDITED_DOC,
                    },
                ),
                text_turn("I replaced the note body."),
            ]
        )
        service = _make_service(provider=provider)

        # Act
        result = service.run_turn(execution.id)

        # Assert
        execution.refresh_from_db()
        self.note.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.SUCCEEDED)
        self.assertEqual(result["final_text"], "I replaced the note body.")
        # Stored as a JSON-encoded string, the shape the frontend editor loads.
        self.assertEqual(json.loads(self.note.latest_version.json), EDITED_DOC)
        reply = execution.generated_chat_message
        self.assertIsNotNone(reply)
        self.assertEqual(reply.content, "I replaced the note body.")
        # The user prompt the model saw is the chat message, not a wrapper.
        first_call = provider.calls[0]
        self.assertEqual(first_call[0].content[0].text, "Replace the note body.")

    def test_run_turn_refuses_notes_outside_the_conversation(self):
        # Arrange: a second note the same user administers; the model tries
        # to read it from this note's chat.
        other_note, _other_content = create_note(self.user, organization=None)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=other_note.unified_document.id,
            user=self.user,
        )
        execution, _delay = self._submit("Summarize my other note.")
        provider = FakeProvider(
            [
                tool_turn("t1", "read_note", {"note_id": other_note.id}),
                text_turn("Done."),
            ]
        )
        service = _make_service(provider=provider)

        # Act
        service.run_turn(execution.id)

        # Assert: the tool refused, so the other note never reached the model.
        tool_results = [
            block
            for message in provider.calls[1]
            for block in message.content
            if getattr(block, "type", "") == "tool_result"
        ]
        self.assertEqual(len(tool_results), 1)
        self.assertIn("not found or not accessible", tool_results[0].content["error"])

    def test_run_turn_uses_the_recorded_model(self):
        # Arrange: the settings default changed after this turn was queued;
        # the row still names the model it was submitted with.
        execution, _delay = self._submit()
        AgentExecution.objects.filter(id=execution.id).update(
            model="bedrock:pinned-model"
        )
        provider = FakeProvider([text_turn("Done.")])
        service = _make_service()

        # Act
        with patch(
            "research_ai.services.notebook_chat.service.resolve_provider",
            return_value=provider,
        ) as resolver:
            result = service.run_turn(execution.id)

        # Assert
        resolver.assert_called_once_with(
            "bedrock:pinned-model", native_tools=frozenset({"web_search"})
        )
        self.assertEqual(result["final_text"], "Done.")

    def test_run_turn_honors_the_recorded_iteration_limit(self):
        # Arrange: the turn was submitted with a one-iteration budget; the
        # provider wants two turns.
        execution, _delay = self._submit()
        stored = AgentExecution.objects.get(id=execution.id).configuration
        stored["max_iterations"] = 1
        AgentExecution.objects.filter(id=execution.id).update(configuration=stored)
        provider = FakeProvider(
            [
                tool_turn("t1", "read_note", {"note_id": self.note.id}),
                text_turn("Too late."),
            ]
        )
        service = _make_service(provider=provider)

        # Act
        result = service.run_turn(execution.id)

        # Assert: the stored budget, not the (larger) settings default, ran.
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.FAILED)
        self.assertEqual(execution.stop_reason, "iteration_limit")
        self.assertIn("error", result)

    def test_submit_message_snapshots_the_token_budget(self):
        # Act
        execution, _delay = self._submit()

        # Assert: null max_tokens is the recorded "model's own ceiling" choice.
        self.assertIsNone(execution.configuration["max_tokens"])

    def test_run_turn_passes_the_model_max_budget_through(self):
        # Arrange
        execution, _delay = self._submit()
        provider = CapturingProvider([text_turn("Done.")])
        service = _make_service(provider=provider)

        # Act
        service.run_turn(execution.id)

        # Assert: None reaches the provider, which resolves its model ceiling.
        self.assertEqual(provider.max_tokens_seen, [None])

    def test_run_turn_honors_the_recorded_max_tokens(self):
        # Arrange: the turn was submitted with a pinned budget; a later
        # settings change must not retroactively alter it.
        execution, _delay = self._submit()
        stored = AgentExecution.objects.get(id=execution.id).configuration
        stored["max_tokens"] = 12345
        AgentExecution.objects.filter(id=execution.id).update(configuration=stored)
        provider = CapturingProvider([text_turn("Done.")])
        service = _make_service(provider=provider)

        # Act
        service.run_turn(execution.id)

        # Assert
        self.assertEqual(provider.max_tokens_seen, [12345])

    def test_truncated_edit_note_call_is_not_dispatched(self):
        # Arrange: the incident shape -- the model's edit_note turn was cut
        # off at the output token limit, so its content never fully arrived.
        execution, _delay = self._submit("Replace the note body.")
        self.note.refresh_from_db()
        original_version_id = self.note.latest_version_id
        provider = FakeProvider(
            [
                tool_turn(
                    "t1",
                    "edit_note",
                    {"note_id": self.note.id},
                    stop_reason=StopReason.MAX_TOKENS,
                ),
                text_turn("The note was too large to rewrite in one pass."),
            ]
        )
        service = _make_service(provider=provider)

        # Act
        result = service.run_turn(execution.id)

        # Assert: nothing was written, the model was told the real cause
        # (not a misleading validation error), and the turn completed.
        execution.refresh_from_db()
        self.note.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.SUCCEEDED)
        self.assertEqual(self.note.latest_version_id, original_version_id)
        tool_results = [
            block
            for message in provider.calls[1]
            for block in message.content
            if getattr(block, "type", "") == "tool_result"
        ]
        self.assertEqual(len(tool_results), 1)
        self.assertTrue(tool_results[0].is_error)
        self.assertIn("truncated", tool_results[0].content["error"])
        self.assertEqual(
            result["final_text"], "The note was too large to rewrite in one pass."
        )

    def test_repeated_failing_edits_are_bounded_by_the_iteration_cap(self):
        # Arrange: the model retries an invalid edit forever; each failure
        # result carries the real error for it to act on, and only the
        # iteration cap bounds the run.
        execution, _delay = self._submit("Replace the note body.")
        stored = AgentExecution.objects.get(id=execution.id).configuration
        stored["max_iterations"] = 4
        AgentExecution.objects.filter(id=execution.id).update(configuration=stored)
        invalid_edit = {
            "note_id": self.note.id,
            "expected_version_id": self.content.id,
            "content": {"type": "paragraph"},
        }
        provider = FakeProvider(
            [tool_turn(f"t{i}", "edit_note", invalid_edit) for i in range(6)]
        )
        service = _make_service(provider=provider)

        # Act
        result = service.run_turn(execution.id)

        # Assert
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.FAILED)
        self.assertEqual(execution.stop_reason, "iteration_limit")
        self.assertEqual(len(provider.calls), 4)
        self.assertIn("error", result)

        # The chat is free again and the next turn chains off the failed run.
        second, _delay = self._submit("Try something else")
        self.assertEqual(second.context_parent_id, execution.id)

    def test_run_turn_provider_failure_marks_execution_failed(self):
        # Arrange
        execution, _delay = self._submit()
        provider = FakeProvider([RuntimeError("provider exploded")])
        service = _make_service(provider=provider)

        # Act
        result = service.run_turn(execution.id)

        # Assert
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.FAILED)
        self.assertIn("provider exploded", result["error"])

    def test_failed_enqueue_fails_the_execution_and_frees_the_conversation(self):
        # Arrange & Act: the broker refuses the task after the turn committed.
        with (
            patch(
                "research_ai.tasks.run_notebook_chat_turn_task.delay",
                side_effect=RuntimeError("broker down"),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            execution = self.service.submit_message(self.note, self.conversation, "Hi")

        # Assert: failed instead of holding the busy check forever.
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.FAILED)
        self.assertIn("broker down", execution.error_message)

        # The conversation is free again for the next message.
        second, _delay = self._submit("again")
        self.assertEqual(second.conversation_id, execution.conversation_id)

    def test_run_turn_duplicate_delivery_is_skipped(self):
        # Arrange: another worker already claimed this execution.
        execution, _delay = self._submit()
        claimed = self.service.chat.executions.claim_pending(execution)
        self.assertIsNotNone(claimed)

        # Act: the same task is delivered a second time.
        result = self.service.run_turn(execution.id)

        # Assert: the duplicate is a no-op and the claim is untouched.
        self.assertTrue(result["skipped"])
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.RUNNING)

    def test_run_turn_skips_cancelled_execution(self):
        # Arrange
        execution, _delay = self._submit()
        AgentExecution.objects.filter(id=execution.id).update(
            status=AgentExecution.Status.CANCELLED
        )

        # Act
        result = self.service.run_turn(execution.id)

        # Assert
        self.assertTrue(result["skipped"])
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.CANCELLED)
        self.assertEqual(result["execution_id"], execution.id)

    def test_run_turn_without_note_link_fails_the_execution(self):
        # Arrange
        execution, _delay = self._submit()
        execution.conversation.note_links.all().delete()

        # Act
        result = self.service.run_turn(execution.id)

        # Assert
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.FAILED)
        self.assertIn("missing", result["error"])

    def test_second_turn_carries_prior_context(self):
        # Arrange: complete a first turn, then run a second one.
        first, _delay = self._submit("First question")
        service = _make_service(provider=FakeProvider([text_turn("First answer")]))
        service.run_turn(first.id)

        second, _delay = self._submit("Second question")
        provider = FakeProvider([text_turn("Second answer")])
        service = _make_service(provider=provider)

        # Act
        service.run_turn(second.id)

        # Assert: the model's context contains the first exchange.
        sent = provider.calls[0]
        texts = [
            block.text
            for message in sent
            for block in message.content
            if hasattr(block, "text")
        ]
        self.assertIn("First question", texts)
        self.assertIn("First answer", texts)
        self.assertIn("Second question", texts)
        self.assertEqual(AgentConversation.objects.filter(user=self.user).count(), 1)


class NotebookChatTitleTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.note = create_note(self.user, organization=None)[0]
        Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note.unified_document.id,
            user=self.user,
        )
        self.service = _make_service()
        self.conversation = self.service.create_conversation(self.note, self.user)

    def _submit(self, text, conversation=None):
        conversation = self.conversation if conversation is None else conversation
        with (
            patch("research_ai.tasks.run_notebook_chat_turn_task.delay"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            return self.service.submit_message(self.note, conversation, text)

    def test_first_message_titles_the_chat_as_one_bounded_line(self):
        # Act
        self._submit("Draft an\nabstract   for this note\n\nplease")

        # Assert
        self.conversation.refresh_from_db()
        self.assertEqual(
            self.conversation.title, "Draft an abstract for this note please"
        )

    def test_long_first_message_is_truncated_in_the_title(self):
        # Act
        self._submit("word " * 100)

        # Assert
        self.conversation.refresh_from_db()
        self.assertLessEqual(len(self.conversation.title), TITLE_MAX_CHARS)
        self.assertTrue(self.conversation.title.startswith("word word"))
        self.assertFalse(self.conversation.title.endswith(" "))

    def test_title_does_not_change_after_the_first_message(self):
        # Arrange
        first = self._submit("Original question")
        AgentExecution.objects.filter(id=first.id).update(
            status=AgentExecution.Status.SUCCEEDED
        )

        # Act
        self._submit("A completely different follow-up")

        # Assert
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.title, "Original question")

    def test_explicit_title_survives_the_first_message(self):
        # Arrange
        named = self.service.create_conversation(
            self.note, self.user, title="Planning thread"
        )

        # Act
        self._submit("Something unrelated", conversation=named)

        # Assert
        named.refresh_from_db()
        self.assertEqual(named.title, "Planning thread")

    def test_rename_conversation_updates_the_title(self):
        # Act
        self.service.rename_conversation(self.conversation, "Literature review")

        # Assert
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.title, "Literature review")


class NotebookChatResolutionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.other_user = user_model.objects.create_user(
            username="other@researchhub_test.com",
            password="password",
            email="other@researchhub_test.com",
        )
        unified_doc_ct = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
        self.note = create_note(self.user, organization=None)[0]
        self.other_note = create_note(self.user, organization=None)[0]
        for note in (self.note, self.other_note):
            Permission.objects.create(
                access_type=ADMIN,
                content_type=unified_doc_ct,
                object_id=note.unified_document.id,
                user=self.user,
            )
        self.service = _make_service()
        self.conversation = self.service.create_conversation(self.note, self.user)

    def test_get_conversation_resolves_the_users_chat_on_the_note(self):
        # Act & Assert
        self.assertEqual(
            self.service.get_conversation(self.note, self.user, self.conversation.id),
            self.conversation,
        )

    def test_get_conversation_rejects_other_users_notes_and_workflows(self):
        # Arrange
        other_users_chat = self.service.create_conversation(self.note, self.other_user)
        other_notes_chat = self.service.create_conversation(self.other_note, self.user)
        other_workflow = AgentConversation.objects.create(
            user=self.user, workflow="proposal_draft"
        )
        NoteAgentConversation.objects.create(
            note=self.note, conversation=other_workflow
        )

        # Act & Assert: none of them resolve for (note, user, notebook_chat).
        for conversation in (other_users_chat, other_notes_chat, other_workflow):
            self.assertIsNone(
                self.service.get_conversation(self.note, self.user, conversation.id)
            )

    def test_list_conversations_projects_the_users_chats_newest_first(self):
        # Arrange: a second chat with a pending turn; another user's chat that
        # must stay invisible.
        second = self.service.create_conversation(self.note, self.user)
        with (
            patch("research_ai.tasks.run_notebook_chat_turn_task.delay"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.service.submit_message(self.note, second, "Find related work")
        self.service.create_conversation(self.note, self.other_user)

        # Act
        listing = self.service.list_conversations(self.note, self.user)

        # Assert: the chat with the newest activity leads, carrying its
        # derived title, message preview, and busy flag; the untouched chat
        # reports none of those.
        self.assertEqual(
            [entry["id"] for entry in listing], [second.id, self.conversation.id]
        )
        active, idle = listing
        self.assertEqual(active["title"], "Find related work")
        self.assertEqual(active["last_message_preview"], "Find related work")
        self.assertTrue(active["has_active_turn"])
        self.assertEqual(idle["title"], "")
        self.assertIsNone(idle["last_message_preview"])
        self.assertFalse(idle["has_active_turn"])


class CancellingProvider(FakeProvider):
    """Seals the execution mid-turn, like a cancel landing during the call."""

    def __init__(self, turns, execution_id):
        super().__init__(turns)
        self.execution_id = execution_id

    def complete(self, **kwargs):
        AgentExecution.objects.filter(id=self.execution_id).update(
            status=AgentExecution.Status.CANCELLED
        )
        return super().complete(**kwargs)


class NotebookChatEventEmissionTests(TestCase):
    """Where the service nudges the chat's WebSocket group.

    The publisher is a Mock: the contract under test is which lifecycle
    points emit which kind, always naming the right conversation and
    execution. Commit deferral, group naming, and delivery are the
    publisher's and consumer's own tests.
    """

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.note = create_note(self.user, organization=None)[0]
        Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note.unified_document.id,
            user=self.user,
        )
        self.publisher = Mock()
        self.service = _make_service(event_publisher=self.publisher)
        self.conversation = self.service.create_conversation(self.note, self.user)

    def _submit(self, text="Please add a summary."):
        with (
            patch("research_ai.tasks.run_notebook_chat_turn_task.delay"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            return self.service.submit_message(self.note, self.conversation, text)

    @staticmethod
    def _events(publisher):
        return [call.args for call in publisher.publish.call_args_list]

    def test_submit_message_publishes_turn_queued(self):
        # Act
        execution = self._submit()

        # Assert
        self.publisher.publish.assert_called_once_with(
            self.conversation.id, execution.id, TURN_QUEUED
        )

    def test_run_turn_publishes_progress_then_finished(self):
        # Arrange
        execution = self._submit()
        run_publisher = Mock()
        runner = _make_service(
            provider=FakeProvider([text_turn("Done.")]),
            event_publisher=run_publisher,
        )

        # Act
        runner.run_turn(execution.id)

        # Assert: every durable write nudged, the settled turn last, and each
        # event names this conversation and execution.
        events = self._events(run_publisher)
        kinds = [kind for _, _, kind in events]
        self.assertIn(TURN_PROGRESS, kinds)
        self.assertEqual(kinds[-1], TURN_FINISHED)
        for conversation_id, execution_id, _ in events:
            self.assertEqual(conversation_id, self.conversation.id)
            self.assertEqual(execution_id, execution.id)

    def test_run_turn_provider_failure_publishes_turn_failed(self):
        # Arrange
        execution = self._submit()
        run_publisher = Mock()
        runner = _make_service(
            provider=FakeProvider([RuntimeError("provider exploded")]),
            event_publisher=run_publisher,
        )

        # Act
        runner.run_turn(execution.id)

        # Assert
        kinds = [kind for _, _, kind in self._events(run_publisher)]
        self.assertEqual(kinds[-1], TURN_FAILED)
        self.assertNotIn(TURN_FINISHED, kinds)

    def test_cancelled_mid_run_turn_publishes_no_failure(self):
        # Arrange: the cancel lands while the model call is in flight, so the
        # worker's next durable write is refused. Subscribers already got
        # turn_cancelled from the cancel path; nothing here may contradict it.
        execution = self._submit()
        run_publisher = Mock()
        runner = _make_service(
            provider=CancellingProvider([text_turn("Too late.")], execution.id),
            event_publisher=run_publisher,
        )

        # Act
        runner.run_turn(execution.id)

        # Assert: the turn stays cancelled and no terminal event was pushed.
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.CANCELLED)
        kinds = [kind for _, _, kind in self._events(run_publisher)]
        self.assertNotIn(TURN_FAILED, kinds)
        self.assertNotIn(TURN_FINISHED, kinds)

    def test_cancelled_just_before_the_finish_publishes_no_finished(self):
        # Arrange: the narrowest cancellation window -- after the closing
        # assistant message was durably recorded, before the terminal hook
        # runs. The recorder discards the finish, so no event may claim it.
        execution = self._submit()
        run_publisher = Mock()
        runner = _make_service(
            provider=FakeProvider([text_turn("Almost made it.")]),
            event_publisher=run_publisher,
        )
        original = DatabaseAgentRecorder.on_run_finished

        def _cancel_then_finish(recorder, result):
            AgentExecution.objects.filter(id=recorder.execution.id).update(
                status=AgentExecution.Status.CANCELLED
            )
            return original(recorder, result)

        # Act
        with patch.object(
            DatabaseAgentRecorder, "on_run_finished", _cancel_then_finish
        ):
            runner.run_turn(execution.id)

        # Assert: the cancellation stands and neither terminal kind was
        # pushed over the turn_cancelled the cancel path already published.
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.CANCELLED)
        kinds = [kind for _, _, kind in self._events(run_publisher)]
        self.assertIn(TURN_PROGRESS, kinds)
        self.assertNotIn(TURN_FINISHED, kinds)
        self.assertNotIn(TURN_FAILED, kinds)

    def test_run_turn_duplicate_delivery_publishes_nothing(self):
        # Arrange: another worker already claimed this execution.
        execution = self._submit()
        self.assertIsNotNone(self.service.chat.executions.claim_pending(execution))
        run_publisher = Mock()
        runner = _make_service(event_publisher=run_publisher)

        # Act
        result = runner.run_turn(execution.id)

        # Assert: a skipped delivery changed nothing, so it announces nothing.
        self.assertTrue(result["skipped"])
        run_publisher.publish.assert_not_called()

    def test_cancel_active_turn_publishes_turn_cancelled(self):
        # Arrange
        execution = self._submit()

        # Act
        with self.captureOnCommitCallbacks(execute=True):
            cancelled = self.service.cancel_active_turn(self.conversation)

        # Assert
        self.assertIsNotNone(cancelled)
        self.assertEqual(
            self.publisher.publish.call_args.args,
            (self.conversation.id, execution.id, TURN_CANCELLED),
        )

    def test_cancel_that_lost_the_race_publishes_nothing(self):
        # Arrange: the turn goes terminal between the scan and the
        # transition, so the cancel service refuses it.
        self._submit()
        cancel_publisher = Mock()
        cancels = Mock()
        cancels.cancel.return_value = False
        service = _make_service(
            event_publisher=cancel_publisher, cancel_service=cancels
        )

        # Act
        cancelled = service.cancel_active_turn(self.conversation)

        # Assert: no event may announce a cancellation that did not happen.
        self.assertIsNone(cancelled)
        cancel_publisher.publish.assert_not_called()

    def test_cancel_without_active_turn_publishes_nothing(self):
        # Act
        cancelled = self.service.cancel_active_turn(self.conversation)

        # Assert
        self.assertIsNone(cancelled)
        self.publisher.publish.assert_not_called()


class NotebookChatEventSendOrderTests(TransactionTestCase):
    """Send order under autocommit, where ``on_commit`` runs immediately.

    The ``TestCase`` suites above cannot see this interleaving: their
    wrapping transaction defers every callback to one commit point.
    """

    def test_a_refused_broker_sends_queued_before_failed(self):
        # Arrange: a real publisher over a recording layer, so send order --
        # not publish() call order -- is what is asserted.
        user = get_user_model().objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        note = create_note(user, organization=None)[0]
        layer = FakeChannelLayer()
        service = _make_service(
            event_publisher=ConversationEventPublisher(channel_layer=layer)
        )
        conversation = service.create_conversation(note, user)

        # Act: the broker refuses, failing the turn synchronously inside the
        # scheduling step.
        with patch(
            "research_ai.tasks.run_notebook_chat_turn_task.delay",
            side_effect=RuntimeError("broker down"),
        ):
            execution = service.submit_message(note, conversation, "Hello")

        # Assert: queued goes out before the refusal's failure, each naming
        # this conversation and execution.
        self.assertEqual(
            [message["data"] for _group, message in layer.sent],
            [
                {
                    "conversation_id": conversation.id,
                    "execution_id": execution.id,
                    "kind": kind,
                }
                for kind in (TURN_QUEUED, TURN_FAILED)
            ],
        )
