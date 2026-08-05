import json
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APITestCase

from note.tests.helpers import create_note
from research_ai.models import (
    AgentConversation,
    AgentExecution,
    AgentExecutionMessage,
)
from research_ai.services.notebook_chat import NotebookChatService
from research_ai.tests.agent.persistence_test_helpers import (
    FakeProvider,
    text_turn,
    tool_turn,
)
from researchhub_access_group.constants import ADMIN
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument

PUBLIC_EVENT_KEYS = {
    "type",
    "tool",
    "label",
    "status",
    "started_at",
    "finished_at",
    "detail",
    "note_version_id",
    "sources",
}

EDITED_DOC = {
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Edited by the assistant"}],
        }
    ],
}


def _make_service(provider=None, web_search_client=None, oa_client=None):
    return NotebookChatService(
        provider=provider,
        oa_client=Mock() if oa_client is None else oa_client,
        web_search_client=(
            Mock(configured=False) if web_search_client is None else web_search_client
        ),
    )


class NotebookChatActivityTests(TestCase):
    """Activity feeds produced by real turns, read via ``representation``."""

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

    def _run_turn(
        self,
        provider_turns,
        text="Please help.",
        web_search_client=None,
        oa_client=None,
    ):
        service = _make_service()
        with (
            patch("research_ai.tasks.run_notebook_chat_turn_task.delay"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            execution = service.submit_message(self.note, self.user, text)
        runner = _make_service(
            provider=FakeProvider(provider_turns),
            web_search_client=web_search_client,
            oa_client=oa_client,
        )
        runner.run_turn(execution.id)
        return execution

    def _activity(self, execution):
        data = _make_service().representation(execution.conversation)
        by_id = {entry["id"]: entry for entry in data["executions"]}
        return by_id[execution.id]["activity"]

    def test_note_tool_calls_report_labels_statuses_and_note_version(self):
        # Arrange
        execution = self._run_turn(
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
                text_turn("Done."),
            ]
        )

        # Act
        activity = self._activity(execution)

        # Assert
        self.note.refresh_from_db()
        self.assertEqual(
            [event["tool"] for event in activity], (["read_note", "edit_note"])
        )
        read, edit = activity
        self.assertEqual(read["label"], "Read the note")
        self.assertEqual(read["status"], "succeeded")
        self.assertIsNotNone(read["started_at"])
        self.assertIsNotNone(read["finished_at"])
        self.assertEqual(edit["label"], "Edited the note")
        self.assertEqual(edit["status"], "succeeded")
        # The signal an open editor uses to reload the note.
        self.assertEqual(edit["note_version_id"], self.note.latest_version_id)

    def test_activity_never_carries_raw_tool_payloads(self):
        # Arrange: an edit turn, whose tool traffic contains the whole
        # document twice (edit input and read_note result).
        execution = self._run_turn(
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
                text_turn("Done."),
            ]
        )

        # Act
        activity = self._activity(execution)

        # Assert: fixed public shape only, and no document text leaks through.
        for event in activity:
            self.assertLessEqual(set(event), PUBLIC_EVENT_KEYS)
        serialized = json.dumps(activity, default=str)
        self.assertNotIn("Edited by the assistant", serialized)

    def test_web_search_reports_query_and_citation_sources(self):
        # Arrange
        client = Mock(configured=True)
        client.search.return_value = [
            {
                "title": "Perovskite review",
                "url": "https://example.org/review",
                "description": "long snippet the user never needs",
                "age": "3 days",
            }
        ]
        execution = self._run_turn(
            [
                tool_turn("t1", "web_search", {"query": "perovskite stability"}),
                text_turn("Here is what I found."),
            ],
            web_search_client=client,
        )

        # Act
        activity = self._activity(execution)

        # Assert: the query is echoed and sources reduce to title/url pairs.
        (event,) = activity
        self.assertEqual(event["label"], "Searched the web")
        self.assertEqual(event["status"], "succeeded")
        self.assertEqual(event["detail"], "perovskite stability")
        self.assertEqual(
            event["sources"],
            [{"title": "Perovskite review", "url": "https://example.org/review"}],
        )

    def test_scholarly_tools_report_names_and_citation_sources(self):
        # Arrange: a resolved author whose works ground the turn's citations.
        # The work has no readable PDF, so the full-text read falls back to
        # the abstract without touching the network.
        author = {"id": "https://openalex.org/A1", "display_name": "Jennifer Doudna"}
        work = Mock()
        work.as_dict.return_value = {
            "title": "CRISPR paper",
            "source_url": "https://doi.org/10.1000/crispr",
            "pdf_url": "",
            "abstract": "An abstract the user never needs to see raw.",
        }
        oa_client = Mock()
        oa_client.search_authors_via_name.return_value = {"results": [author]}
        oa_client.get_author.return_value = author
        oa_client.get_works_typed.return_value = [work]
        execution = self._run_turn(
            [
                tool_turn("t1", "search_authors", {"name": "Jennifer Doudna"}),
                tool_turn("t2", "get_author", {"openalex_author_id": author["id"]}),
                tool_turn(
                    "t3", "get_author_works", {"openalex_author_id": author["id"]}
                ),
                tool_turn(
                    "t4",
                    "get_work_fulltext",
                    {"source_url": "https://doi.org/10.1000/crispr"},
                ),
                text_turn("Done."),
            ],
            oa_client=oa_client,
        )

        # Act
        activity = self._activity(execution)

        # Assert: names and citations surface; abstracts and metadata do not.
        searched, looked_up, works, read_paper = activity
        self.assertEqual(searched["label"], "Searched scholarly authors")
        self.assertEqual(searched["detail"], "Jennifer Doudna")
        self.assertNotIn("sources", searched)
        self.assertEqual(looked_up["label"], "Looked up an author")
        self.assertEqual(looked_up["detail"], "Jennifer Doudna")
        expected_source = {
            "title": "CRISPR paper",
            "url": "https://doi.org/10.1000/crispr",
        }
        self.assertEqual(works["label"], "Fetched an author's publications")
        self.assertEqual(works["status"], "succeeded")
        self.assertEqual(works["sources"], [expected_source])
        self.assertEqual(read_paper["label"], "Read a paper")
        self.assertEqual(read_paper["status"], "succeeded")
        self.assertEqual(read_paper["sources"], [expected_source])
        for event in activity:
            self.assertLessEqual(set(event), PUBLIC_EVENT_KEYS)
        self.assertNotIn("abstract the user", json.dumps(activity, default=str))

    def test_failed_tool_call_reports_failed_without_error_text(self):
        # Arrange: web search is unconfigured, so the tool returns an error
        # written for the model.
        execution = self._run_turn(
            [
                tool_turn("t1", "web_search", {"query": "anything"}),
                text_turn("I could not search."),
            ]
        )

        # Act
        activity = self._activity(execution)

        # Assert
        (event,) = activity
        self.assertEqual(event["status"], "failed")
        self.assertNotIn("sources", event)
        self.assertNotIn("not configured", json.dumps(activity, default=str))


class NotebookChatActivityProjectionTests(TestCase):
    """Trace shapes a live run cannot conveniently produce, built directly."""

    def setUp(self):
        self.service = NotebookChatService()
        self.conversation = AgentConversation.objects.create(workflow="notebook_chat")
        self.execution = AgentExecution.objects.create(
            conversation=self.conversation,
            attempt=1,
            status=AgentExecution.Status.RUNNING,
        )

    def _add_trace_row(self, sequence, content, provenance):
        AgentExecutionMessage.objects.create(
            conversation=self.conversation,
            execution=self.execution,
            sequence=sequence,
            execution_sequence=sequence,
            role="assistant",
            provenance=provenance,
            content=content,
        )

    def _single_event(self):
        data = self.service.representation(self.conversation)
        (execution,) = data["executions"]
        (event,) = execution["activity"]
        return event

    def test_open_call_is_in_progress_while_running_then_interrupted(self):
        # Arrange: a tool call whose result row never landed.
        self._add_trace_row(
            1,
            [{"type": "tool_use", "id": "t1", "name": "read_note", "input": {}}],
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act & Assert: the live turn shows it running...
        self.assertEqual(self._single_event()["status"], "in_progress")

        # ...and once the turn is over, the open call is reported interrupted.
        self.execution.status = AgentExecution.Status.FAILED
        self.execution.save(update_fields=["status"])
        self.assertEqual(self._single_event()["status"], "interrupted")

    def test_server_side_web_search_blocks_produce_a_sourced_event(self):
        # Arrange: the provider ran web_search itself; request and result are
        # opaque provider blocks on the same assistant turn.
        self._add_trace_row(
            1,
            [
                {
                    "type": "server_tool",
                    "data": {
                        "type": "server_tool_use",
                        "id": "s1",
                        "name": "web_search",
                        "input": {"query": "solid state batteries"},
                    },
                },
                {
                    "type": "server_tool",
                    "data": {
                        "type": "web_search_tool_result",
                        "tool_use_id": "s1",
                        "content": [
                            {
                                "type": "web_search_result",
                                "url": "https://example.org/paper",
                                "title": "Battery paper",
                                "encrypted_content": "opaque-provider-state",
                            }
                        ],
                    },
                },
            ],
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act
        event = self._single_event()

        # Assert: same public shape as the local tool, provider payload dropped.
        self.assertEqual(event["label"], "Searched the web")
        self.assertEqual(event["status"], "succeeded")
        self.assertEqual(event["detail"], "solid state batteries")
        self.assertEqual(
            event["sources"],
            [{"title": "Battery paper", "url": "https://example.org/paper"}],
        )
        self.assertNotIn("opaque-provider-state", json.dumps(event, default=str))

    def test_failed_server_side_call_reports_failed(self):
        # Arrange: the provider reports a server tool failure as a single
        # error object instead of a result list.
        self._add_trace_row(
            1,
            [
                {
                    "type": "server_tool",
                    "data": {
                        "type": "server_tool_use",
                        "id": "s1",
                        "name": "web_search",
                        "input": {"query": "anything"},
                    },
                },
                {
                    "type": "server_tool",
                    "data": {
                        "type": "web_search_tool_result",
                        "tool_use_id": "s1",
                        "content": {
                            "type": "web_search_tool_result_error",
                            "error_code": "max_uses_exceeded",
                        },
                    },
                },
            ],
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act
        event = self._single_event()

        # Assert
        self.assertEqual(event["status"], "failed")
        self.assertNotIn("sources", event)
        self.assertNotIn("max_uses_exceeded", json.dumps(event, default=str))


class NotebookChatActivityViewTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.owner.moderator = True
        self.owner.save(update_fields=["moderator"])
        self.note, self.content = create_note(self.owner, organization=None)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note.unified_document.id,
            user=self.owner,
        )
        self.chat_url = f"/api/research_ai/notebook/notes/{self.note.id}/chat/"

    def test_get_chat_includes_each_turns_activity(self):
        # Arrange: a submitted turn has no activity yet; a completed turn has
        # its tool calls.
        self.client.force_authenticate(self.owner)
        with patch("research_ai.tasks.run_notebook_chat_turn_task.delay"):
            posted = self.client.post(
                f"{self.chat_url}messages/",
                {"message": "Summarize the note"},
                format="json",
            )
        before = self.client.get(self.chat_url)
        self.assertEqual(before.data["executions"][0]["activity"], [])

        _make_service(
            provider=FakeProvider(
                [
                    tool_turn("t1", "read_note", {"note_id": self.note.id}),
                    text_turn("Summary."),
                ]
            )
        ).run_turn(posted.data["execution_id"])

        # Act
        response = self.client.get(self.chat_url)

        # Assert
        (execution,) = response.data["executions"]
        (event,) = execution["activity"]
        self.assertEqual(event["tool"], "read_note")
        self.assertEqual(event["label"], "Read the note")
        self.assertEqual(event["status"], "succeeded")
