import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from note.models import Note
from note.tests.helpers import create_note
from purchase.models import Grant
from research_ai.models import AgentExecution
from research_ai.services.agent.types import TurnUsage
from research_ai.services.assistant_chat import WORKFLOW, AssistantChatService
from research_ai.services.notebook_chat import NotebookChatService
from research_ai.services.usage_budget import budget_status
from research_ai.tests.agent.persistence_test_helpers import (
    FakeProvider,
    text_turn,
    tool_turn,
)
from researchhub_access_group.constants import ADMIN, NO_ACCESS
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)

MODEL_SETTINGS = {
    "ANTHROPIC_AWS_WORKSPACE_ID": "ws-test",
    "AWS_REGION_NAME": "us-east-1",
    "OPENROUTER_API_KEY": "or-test",
}
INSERT_BODY = [{"op": "insert", "at": 0, "blocks": ["Drafted by the assistant"]}]


class LazyProvider(FakeProvider):
    """A fake whose turns may be callables built once earlier turns ran.

    A real model reads the created note's id from the create_note result;
    the fake builds its edit_note turn from the database instead.
    """

    def complete(self, **kwargs):
        if callable(self.turns[0]):
            self.turns[0] = self.turns[0]()
        return super().complete(**kwargs)


def _make_service(provider=None, **kwargs):
    return AssistantChatService(
        provider=provider,
        oa_client=Mock(),
        web_search_client=Mock(configured=False),
        **kwargs,
    )


@override_settings(**MODEL_SETTINGS)
class AssistantChatServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
            is_staff=True,
        )
        self.service = _make_service()
        self.conversation = self.service.create_conversation(self.user)

    def _submit(self, text="Draft a proposal outline.", **kwargs):
        with (
            patch("research_ai.tasks.run_notebook_chat_turn_task.delay") as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            execution = self.service.submit_message(self.conversation, text, **kwargs)
        return execution, delay

    def _run(self, execution, turns):
        result = _make_service(provider=LazyProvider(turns)).run_turn(execution.id)
        execution.refresh_from_db()
        return result

    def _activity(self, attempt_index):
        representation = self.service.representation(self.conversation)
        return representation["executions"][attempt_index]["activity"]

    def test_submit_message_prepares_a_note_less_turn(self):
        # Act
        execution, delay = self._submit()

        # Assert
        self.assertEqual(execution.conversation.workflow, WORKFLOW)
        self.assertEqual(execution.conversation.user, self.user)
        self.assertEqual(execution.status, AgentExecution.Status.PENDING)
        self.assertNotIn("note_id", execution.configuration)
        self.assertIn("create_note", execution.system_prompt)
        self.assertIn("has not created any notes yet", execution.system_prompt)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.title, "Draft a proposal outline.")
        delay.assert_called_once_with(execution.id)

    def test_run_turn_can_create_and_populate_a_note(self):
        # Arrange: the model creates a note, writes into it, and replies.
        execution, _delay = self._submit()

        def edit_the_new_note():
            note = Note.objects.get(title="Proposal outline")
            return tool_turn(
                "t2",
                "edit_note",
                {
                    "note_id": note.id,
                    "expected_version_id": None,
                    "edits": INSERT_BODY,
                },
            )

        # Act
        result = self._run(
            execution,
            [
                tool_turn(
                    "t1",
                    "create_note",
                    {"title": "  Proposal   outline ", "kind": "preregistration"},
                ),
                edit_the_new_note,
                text_turn("I drafted the outline into a new note."),
            ],
        )

        # Assert: the note exists, is private to the user, holds the body,
        # and is attached to the conversation.
        self.assertEqual(execution.status, AgentExecution.Status.SUCCEEDED)
        self.assertEqual(result["final_text"], "I drafted the outline into a new note.")
        note = Note.objects.get(title="Proposal outline")
        self.assertEqual(note.document_type, PREREGISTRATION)
        self.assertEqual(note.created_by, self.user)
        self.assertEqual(note.organization, self.user.organization)
        self.assertEqual(json.loads(note.latest_version.json)["type"], "doc")
        self.assertEqual(note.latest_version.plain_text, "Drafted by the assistant")
        permissions = note.unified_document.permissions
        self.assertTrue(permissions.filter(user=self.user, access_type=ADMIN).exists())
        self.assertTrue(
            permissions.filter(
                organization=self.user.organization, access_type=NO_ACCESS
            ).exists()
        )
        self.assertTrue(self.conversation.note_links.filter(note=note).exists())
        representation = self.service.representation(self.conversation)
        self.assertEqual(
            representation["notes"],
            [
                {
                    "id": note.id,
                    "title": "Proposal outline",
                    "document_type": PREREGISTRATION,
                }
            ],
        )
        created = [
            event for event in self._activity(0) if event.get("tool") == "create_note"
        ]
        self.assertEqual(created[0]["label"], "Created a note")
        self.assertEqual(created[0]["note_id"], note.id)
        self.assertEqual(created[0]["note_title"], "Proposal outline")
        self.assertEqual(created[0]["note_document_type"], PREREGISTRATION)

    def test_run_turn_can_create_a_grant_note(self):
        # Arrange
        execution, _delay = self._submit("Draft an RFP for soil research.")

        # Act
        self._run(
            execution,
            [
                tool_turn("t1", "create_note", {"title": "Soil RFP", "kind": "grant"}),
                text_turn("Created the RFP note."),
            ],
        )

        # Assert
        note = self.conversation.note_links.get().note
        self.assertEqual(note.document_type, GRANT)
        self.assertEqual(note.title, "Soil RFP")

    def test_run_turn_can_select_an_rfp_on_a_created_preregistration(self):
        # Arrange: an open grant the user can see, and a preregistration the
        # chat creates in the same turn it selects the RFP on.
        grant = self._open_grant()
        execution, _delay = self._submit("Apply to the reproducibility RFP.")

        def select_on_the_new_note():
            note = Note.objects.get(title="Reproducibility proposal")
            return tool_turn(
                "t2",
                "set_selected_rfp",
                {"note_id": note.id, "grant_id": grant.id},
            )

        def read_from_the_new_note():
            note = Note.objects.get(title="Reproducibility proposal")
            return tool_turn("t3", "read_selected_rfp", {"note_id": note.id})

        # Act
        result = self._run(
            execution,
            [
                tool_turn(
                    "t1",
                    "create_note",
                    {"title": "Reproducibility proposal", "kind": "preregistration"},
                ),
                select_on_the_new_note,
                read_from_the_new_note,
                text_turn("The proposal now applies to the reproducibility RFP."),
            ],
        )

        # Assert
        self.assertEqual(
            result["final_text"],
            "The proposal now applies to the reproducibility RFP.",
        )
        note = Note.objects.get(title="Reproducibility proposal")
        self.assertEqual(note.selected_grant, grant)
        statuses = [
            (event["tool"], event["status"])
            for event in self._activity(0)
            if event["type"] == "tool_call"
        ]
        self.assertEqual(
            statuses,
            [
                ("create_note", "succeeded"),
                ("set_selected_rfp", "succeeded"),
                ("read_selected_rfp", "succeeded"),
            ],
        )

    def test_rfp_tools_refuse_notes_outside_the_chat(self):
        # Arrange: a preregistration the user owns but did not create here.
        grant = self._open_grant()
        outside, _content = create_note(self.user, organization=None)
        outside.document_type = PREREGISTRATION
        outside.save(update_fields=["document_type"])
        execution, _delay = self._submit("Apply with my other proposal.")

        # Act
        self._run(
            execution,
            [
                tool_turn(
                    "t1",
                    "set_selected_rfp",
                    {"note_id": outside.id, "grant_id": grant.id},
                ),
                text_turn("Could not."),
            ],
        )

        # Assert
        outside.refresh_from_db()
        self.assertIsNone(outside.selected_grant)
        (selection,) = [
            event
            for event in self._activity(0)
            if event.get("tool") == "set_selected_rfp"
        ]
        self.assertEqual(selection["status"], "failed")

    def _open_grant(self):
        post = create_post(
            created_by=self.user,
            document_type=GRANT,
            title="Reproducibility RFP",
            renderable_text="Applicants must publish their methods.",
        )
        post.unified_document.is_public = True
        post.unified_document.save(update_fields=["is_public"])
        return Grant.objects.create(
            created_by=self.user,
            unified_document=post.unified_document,
            short_title="Reproducibility RFP",
            organization="Research Foundation",
            description="Funding for reproducible research.",
            amount=Decimal("75000.00"),
            currency="USD",
            status=Grant.OPEN,
            end_date=timezone.now() + timedelta(days=30),
        )

    def test_later_turns_see_the_created_notes_and_nothing_else(self):
        # Arrange: one note created by this chat, one the user owns otherwise.
        execution, _delay = self._submit()
        self._run(
            execution,
            [tool_turn("t1", "create_note", {"title": "Mine", "kind": "grant"})],
        )
        own_note = self.conversation.note_links.get().note
        other_note, _content = create_note(self.user, organization=None)

        # Act
        second, _delay = self._submit("Read both notes.")
        result = self._run(
            second,
            [
                tool_turn("t2", "read_note", {"note_id": other_note.id}),
                tool_turn("t3", "read_note", {"note_id": own_note.id}),
                text_turn("Done."),
            ],
        )

        # Assert: the prompt names the created note; the other note is
        # invisible even though the user could open it in the notebook.
        self.assertIn(f'note {own_note.id} ("Mine"), grant', second.system_prompt)
        self.assertNotIn(f"note {other_note.id}", second.system_prompt)
        self.assertEqual(result["final_text"], "Done.")
        reads = [
            event for event in self._activity(1) if event.get("tool") == "read_note"
        ]
        self.assertEqual([event["status"] for event in reads], ["failed", "succeeded"])

    def test_created_note_does_not_list_the_assistant_chat_on_the_note(self):
        # Arrange
        execution, _delay = self._submit()
        self._run(
            execution,
            [tool_turn("t1", "create_note", {"title": "Mine", "kind": "grant"})],
        )
        note = self.conversation.note_links.get().note

        # Act
        notebook_chats = NotebookChatService().list_conversations(note, self.user)

        # Assert
        self.assertEqual(notebook_chats, [])

    def test_run_turn_accounts_usage_to_the_assistant_feature(self):
        # Arrange
        execution, _delay = self._submit(model_ref="claude_platform:claude-opus-5")

        class UsageReportingProvider(FakeProvider):
            def complete(self, **kwargs):
                turn = super().complete(**kwargs)
                kwargs["on_usage"](turn.usage)
                return turn

        provider = UsageReportingProvider(
            [text_turn("Done.", usage=TurnUsage(input_tokens=1000, output_tokens=100))]
        )

        # Act
        _make_service(provider=provider).run_turn(execution.id)

        # Assert
        event = execution.usage_events.get()
        self.assertEqual(event.feature, WORKFLOW)
        self.assertEqual(budget_status(self.user).as_dict()["credits"]["used"], "7.5")

    def test_get_conversation_is_scoped_to_owner_and_workflow(self):
        # Arrange
        user_model = get_user_model()
        other = user_model.objects.create_user(
            username="other@researchhub_test.com",
            password="password",
            email="other@researchhub_test.com",
        )
        note, _content = create_note(self.user, organization=None)
        notebook_chat = NotebookChatService().create_conversation(note, self.user)

        # Act / Assert
        self.assertEqual(
            self.service.get_conversation(self.user, self.conversation.id),
            self.conversation,
        )
        self.assertIsNone(self.service.get_conversation(other, self.conversation.id))
        self.assertIsNone(self.service.get_conversation(self.user, notebook_chat.id))
