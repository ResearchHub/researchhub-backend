import json
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from note.tests.helpers import create_note
from purchase.models import Grant
from purchase.services.grant_search_service import GrantSearchService
from research_ai.models import (
    AgentConversation,
    AgentExecution,
    AgentExecutionMessage,
)
from research_ai.services.agent_persistence.recorder import DatabaseAgentRecorder
from research_ai.services.notebook_chat import ACTIVITY_LIVE, NotebookChatService
from research_ai.services.notebook_chat.service import ACTIVITY_SETTLED_GRACE
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

PUBLIC_NARRATION_KEYS = {"type", "text", "at"}
PUBLIC_THINKING_KEYS = {"type", "text", "at"}


def _tool_calls(activity):
    return [event for event in activity if event["type"] == "tool_call"]


def _narrations(activity):
    return [event for event in activity if event["type"] == "narration"]


def _thinkings(activity):
    return [event for event in activity if event["type"] == "thinking"]


# edit_note input: block operations in the compact dialect (a bare string
# block is a paragraph).
EDIT_NOTE_EDITS = [{"op": "insert", "at": 0, "blocks": ["Edited by the assistant"]}]


def _make_service(
    provider=None, web_search_client=None, oa_client=None, stream_store=None
):
    return NotebookChatService(
        provider=provider,
        oa_client=Mock() if oa_client is None else oa_client,
        web_search_client=(
            Mock(configured=False) if web_search_client is None else web_search_client
        ),
        stream_store=stream_store,
    )


def _settle_beyond_grace(execution_id):
    """Age a settled turn past the live scope's grace window."""
    long_ago = timezone.now() - 2 * ACTIVITY_SETTLED_GRACE
    AgentExecution.objects.filter(id=execution_id).update(
        finished_at=long_ago, last_activity_at=long_ago
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
        self.conversation = _make_service().create_conversation(self.note, self.user)

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
            execution = service.submit_message(self.note, self.conversation, text)
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
                        "edits": EDIT_NOTE_EDITS,
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
            [event["tool"] for event in _tool_calls(activity)],
            (["read_note", "edit_note"]),
        )
        read, edit = _tool_calls(activity)
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
                tool_turn(
                    "t1",
                    "read_note",
                    {"note_id": self.note.id},
                    thinking={
                        "type": "thinking",
                        "thinking": "I should inspect the note first.",
                        "signature": "thinking-signature-sentinel",
                    },
                ),
                tool_turn(
                    "t2",
                    "edit_note",
                    {
                        "note_id": self.note.id,
                        "expected_version_id": self.content.id,
                        "edits": EDIT_NOTE_EDITS,
                    },
                ),
                text_turn("Done."),
            ]
        )

        # Act
        activity = self._activity(execution)

        # Assert: fixed public shape only, and no document text leaks through.
        for event in _tool_calls(activity):
            self.assertLessEqual(set(event), PUBLIC_EVENT_KEYS)
        for event in _narrations(activity):
            self.assertLessEqual(set(event), PUBLIC_NARRATION_KEYS)
        for event in _thinkings(activity):
            self.assertLessEqual(set(event), PUBLIC_THINKING_KEYS)
        serialized = json.dumps(activity, default=str)
        self.assertNotIn("Edited by the assistant", serialized)
        self.assertNotIn("thinking-signature-sentinel", serialized)

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
        (event,) = _tool_calls(activity)
        self.assertEqual(event["label"], "Searched the web")
        self.assertEqual(event["status"], "succeeded")
        self.assertEqual(event["detail"], "perovskite stability")
        self.assertEqual(
            event["sources"],
            [{"title": "Perovskite review", "url": "https://example.org/review"}],
        )

    def test_grant_search_reports_query_and_grant_sources(self):
        # Arrange
        post = Mock(
            id=42,
            slug="neural-biomarkers",
            title="Neural Biomarkers",
            renderable_text="Post body must not enter activity.",
        )
        grant = Mock(
            id=7,
            short_title="Neural Biomarkers",
            organization="Research Foundation",
            description="Private result details must not enter activity.",
            amount="50000.00",
            currency="USD",
            end_date=None,
            application_visibility=Grant.APPLICATION_VISIBILITY_OPTIONAL,
        )
        grant.unified_document.posts.all.return_value = [post]
        with patch.object(GrantSearchService, "search", return_value=[grant]):
            execution = self._run_turn(
                [
                    tool_turn(
                        "t1",
                        "search_grants",
                        {"query": "neural biomarkers"},
                    ),
                    text_turn("Here is a possible grant."),
                ]
            )

        # Act
        activity = self._activity(execution)

        # Assert
        (event,) = _tool_calls(activity)
        self.assertEqual(event["label"], "Searched grants")
        self.assertEqual(event["detail"], "neural biomarkers")
        self.assertEqual(
            event["sources"],
            [
                {
                    "title": "Neural Biomarkers",
                    "url": ("http://localhost:3000/grant/42/neural-biomarkers"),
                }
            ],
        )
        self.assertNotIn("Private result details", json.dumps(activity, default=str))
        self.assertNotIn("Post body must not enter", json.dumps(activity, default=str))

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
        searched, looked_up, works, read_paper = _tool_calls(activity)
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
        for event in _tool_calls(activity):
            self.assertLessEqual(set(event), PUBLIC_EVENT_KEYS)
        self.assertNotIn("abstract the user", json.dumps(activity, default=str))

    def test_narration_interleaves_with_tool_calls_but_omits_the_answer(self):
        # Arrange: the fake turns narrate ("calling read_note") before acting,
        # then answer in plain text.
        execution = self._run_turn(
            [
                tool_turn("t1", "read_note", {"note_id": self.note.id}),
                text_turn("Here is the summary."),
            ]
        )

        # Act
        activity = self._activity(execution)

        # Assert: narration precedes the call it explains, and the final answer
        # is absent from the feed because the chat publishes it as a message.
        self.assertEqual(
            [
                (event["type"], event.get("text") or event.get("tool"))
                for event in activity
            ],
            [("narration", "calling read_note"), ("tool_call", "read_note")],
        )
        published = execution.conversation.chat_messages.filter(
            role="ASSISTANT"
        ).values_list("content", flat=True)
        self.assertEqual(list(published), ["Here is the summary."])

    def test_thinking_traces_surface_as_feed_events(self):
        # Arrange
        execution = self._run_turn(
            [
                tool_turn(
                    "t1",
                    "read_note",
                    {"note_id": self.note.id},
                    thinking={
                        "type": "thinking",
                        "thinking": "I should read the note before answering.",
                        "signature": "sig-opaque",
                    },
                ),
                text_turn("Here is the summary."),
            ]
        )

        # Act
        activity = self._activity(execution)

        # Assert
        self.assertEqual(
            [
                (event["type"], event.get("text") or event.get("tool"))
                for event in activity
            ],
            [
                ("thinking", "I should read the note before answering."),
                ("narration", "calling read_note"),
                ("tool_call", "read_note"),
            ],
        )
        (thinking,) = _thinkings(activity)
        self.assertLessEqual(set(thinking), PUBLIC_THINKING_KEYS)
        self.assertNotIn("sig-opaque", json.dumps(activity, default=str))

    def test_live_scope_recomputes_only_the_turns_that_can_still_change(self):
        # Arrange: two finished turns, the first settled longer ago than the
        # grace window -- every poll since has had its settled feed.
        first = self._run_turn(
            [
                tool_turn("t1", "read_note", {"note_id": self.note.id}),
                text_turn("First."),
            ]
        )
        _settle_beyond_grace(first.id)
        second = self._run_turn(
            [
                tool_turn("t2", "read_note", {"note_id": self.note.id}),
                text_turn("Second."),
            ],
            text="And again.",
        )

        # Act
        service = _make_service()
        full = service.representation(first.conversation)
        live = service.representation(first.conversation, activity_scope=ACTIVITY_LIVE)

        # Assert: the full projection carries both feeds; the polling projection
        # omits the settled turn's key entirely -- not an empty list, which
        # would read as "this turn used no tools".
        full_by_id = {entry["id"]: entry for entry in full["executions"]}
        live_by_id = {entry["id"]: entry for entry in live["executions"]}
        self.assertEqual(len(_tool_calls(full_by_id[first.id]["activity"])), 1)
        self.assertEqual(len(_tool_calls(full_by_id[second.id]["activity"])), 1)
        self.assertNotIn("activity", live_by_id[first.id])
        self.assertEqual(len(_tool_calls(live_by_id[second.id]["activity"])), 1)

    def test_just_settled_turn_keeps_its_feed_while_a_new_turn_displaces_it(self):
        # Arrange: the cancel-then-rephrase shape. A turn settles and a new
        # message lands before the client's next poll, so the settled turn is
        # neither active nor newest -- only the grace window can still hand
        # over its settled feed, without which the client's cached copy shows
        # it mid-flight forever.
        old = self._run_turn(
            [
                tool_turn("t1", "read_note", {"note_id": self.note.id}),
                text_turn("First."),
            ]
        )
        _settle_beyond_grace(old.id)
        recent = self._run_turn(
            [
                tool_turn("t2", "read_note", {"note_id": self.note.id}),
                text_turn("Second."),
            ],
            text="And again.",
        )
        with (
            patch("research_ai.tasks.run_notebook_chat_turn_task.delay"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            queued = _make_service().submit_message(
                self.note, self.conversation, "Rephrased."
            )

        # Act
        live = _make_service().representation(
            old.conversation, activity_scope=ACTIVITY_LIVE
        )

        # Assert: the long-settled turn stays omitted, the just-settled one is
        # delivered despite being displaced, and the queued newest rides along.
        by_id = {entry["id"]: entry for entry in live["executions"]}
        self.assertNotIn("activity", by_id[old.id])
        self.assertEqual(len(_tool_calls(by_id[recent.id]["activity"])), 1)
        self.assertIn("activity", by_id[queued.id])

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
        (event,) = _tool_calls(activity)
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

    def _add_trace_row(self, sequence, content, provenance, role="assistant"):
        AgentExecutionMessage.objects.create(
            conversation=self.conversation,
            execution=self.execution,
            sequence=sequence,
            execution_sequence=sequence,
            role=role,
            provenance=provenance,
            content=content,
        )

    def _finish(self, status=AgentExecution.Status.SUCCEEDED):
        self.execution.status = status
        self.execution.save(update_fields=["status"])

    def _entry(self):
        data = self.service.representation(self.conversation)
        (execution,) = data["executions"]
        return execution

    def _single_event(self):
        data = self.service.representation(self.conversation)
        (execution,) = data["executions"]
        (event,) = _tool_calls(execution["activity"])
        return event

    def test_claude_thinking_block_produces_a_thinking_event(self):
        # Arrange
        self._add_trace_row(
            1,
            [
                {
                    "type": "thinking",
                    "data": {
                        "type": "thinking",
                        "thinking": "I should inspect the evidence.",
                        "signature": "sig-opaque",
                    },
                },
                {"type": "text", "text": "I will inspect the evidence."},
            ],
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act
        activity = self._entry()["activity"]

        # Assert
        (thinking,) = _thinkings(activity)
        self.assertEqual(thinking["text"], "I should inspect the evidence.")
        self.assertEqual(
            [event["type"] for event in activity], ["thinking", "narration"]
        )
        self.assertNotIn("sig-opaque", json.dumps(activity, default=str))

    def test_active_turn_includes_reconnectable_stream_snapshot(self):
        # Arrange
        snapshot = {
            "id": f"{self.execution.id}:1",
            "sequence": 3,
            "iteration": 1,
            "items": [
                {
                    "id": "iteration-1:block-0:narration",
                    "type": "narration",
                    "text": "Partial answer",
                    "at": timezone.now().isoformat(),
                }
            ],
        }
        stream_store = Mock()
        stream_store.get.return_value = snapshot
        service = _make_service(stream_store=stream_store)

        # Act
        data = service.representation(self.conversation)
        (execution,) = data["executions"]

        # Assert
        self.assertEqual(execution["stream"], snapshot)
        self.assertEqual(
            execution["phase"],
            {"state": "responding", "label": "Writing a response"},
        )

    def test_stream_cache_failure_is_treated_as_a_missing_snapshot(self):
        # Arrange
        stream_store = Mock()
        stream_store.get.side_effect = RuntimeError("redis down")
        service = _make_service(stream_store=stream_store)

        # Act
        with self.assertLogs(
            "research_ai.services.notebook_chat.service", level="WARNING"
        ):
            data = service.representation(self.conversation)
        (execution,) = data["executions"]

        # Assert: durable chat state remains available without a preview.
        self.assertIsNone(execution["stream"])
        stream_store.get.assert_called_once_with(self.execution.id)

    def test_terminal_turn_omits_transient_stream_state(self):
        # Arrange
        self._finish()
        stream_store = Mock()
        service = _make_service(stream_store=stream_store)

        # Act
        data = service.representation(self.conversation)
        (execution,) = data["executions"]

        # Assert
        self.assertNotIn("stream", execution)
        stream_store.get.assert_not_called()

    def test_bedrock_and_openrouter_thinking_shapes_extract_their_text(self):
        shapes = (
            (
                "bedrock",
                {"reasoningText": {"text": "Bedrock reasoning", "signature": "sig"}},
                "Bedrock reasoning",
            ),
            (
                "openrouter text",
                {"type": "reasoning.text", "text": "OpenRouter reasoning"},
                "OpenRouter reasoning",
            ),
            (
                "openrouter summary",
                {"type": "reasoning.summary", "summary": "Reasoning summary"},
                "Reasoning summary",
            ),
        )
        for name, data, expected in shapes:
            with self.subTest(name=name):
                # Arrange
                AgentExecutionMessage.objects.filter(execution=self.execution).delete()
                self._add_trace_row(
                    1,
                    [{"type": "thinking", "data": data}],
                    AgentExecutionMessage.Provenance.MODEL,
                )

                # Act
                activity = self._entry()["activity"]

                # Assert
                (thinking,) = _thinkings(activity)
                self.assertEqual(thinking["text"], expected)

    def test_unreadable_thinking_blocks_are_skipped(self):
        shapes = (
            (
                "claude redacted",
                {
                    "type": "thinking",
                    "data": {
                        "type": "redacted_thinking",
                        "data": "opaque-blob",
                    },
                },
            ),
            (
                "claude empty",
                {
                    "type": "thinking",
                    "data": {"type": "thinking", "thinking": ""},
                },
            ),
            (
                "bedrock redacted",
                {
                    "type": "thinking",
                    "data": {"redactedContent": "opaque-blob"},
                },
            ),
            (
                "openrouter encrypted",
                {
                    "type": "thinking",
                    "data": {
                        "type": "reasoning.encrypted",
                        "data": "opaque-blob",
                    },
                },
            ),
            ("malformed", {"type": "thinking", "data": "opaque-blob"}),
        )
        for name, block in shapes:
            with self.subTest(name=name):
                # Arrange
                AgentExecutionMessage.objects.filter(execution=self.execution).delete()
                self._add_trace_row(1, [block], AgentExecutionMessage.Provenance.MODEL)

                # Act
                activity = self._entry()["activity"]

                # Assert
                self.assertEqual(_thinkings(activity), [])
                self.assertNotIn("opaque-blob", json.dumps(activity, default=str))

    def test_thinking_survives_when_the_answer_is_published(self):
        # Arrange
        self._add_trace_row(
            1,
            [
                {
                    "type": "thinking",
                    "data": {
                        "type": "thinking",
                        "thinking": "I have enough evidence to answer.",
                    },
                },
                {"type": "text", "text": "Here is the answer."},
            ],
            AgentExecutionMessage.Provenance.MODEL,
        )
        self.execution.status = AgentExecution.Status.SUCCEEDED
        self.execution.publish_output_to_chat = True
        self.execution.final_output = {"text": "Here is the answer."}
        self.execution.save(
            update_fields=["status", "publish_output_to_chat", "final_output"]
        )

        # Act
        activity = self._entry()["activity"]

        # Assert
        self.assertEqual(_narrations(activity), [])
        (thinking,) = _thinkings(activity)
        self.assertEqual(thinking["text"], "I have enough evidence to answer.")

    def test_thinking_text_is_capped(self):
        # Arrange
        self._add_trace_row(
            1,
            [
                {
                    "type": "thinking",
                    "data": {"type": "thinking", "thinking": "x" * 5000},
                }
            ],
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act
        (thinking,) = _thinkings(self._entry()["activity"])

        # Assert
        self.assertEqual(len(thinking["text"]), 4000)

    def test_phase_stays_thinking_when_the_newest_row_is_only_thinking(self):
        # Arrange
        self._add_trace_row(
            1,
            [
                {
                    "type": "thinking",
                    "data": {"type": "thinking", "thinking": "Considering."},
                }
            ],
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act
        phase = self._entry()["phase"]

        # Assert
        self.assertEqual(phase, {"state": "thinking", "label": "Thinking"})

    def test_phase_is_responding_when_narration_follows_thinking(self):
        # Arrange
        self._add_trace_row(
            1,
            [
                {
                    "type": "thinking",
                    "data": {"type": "thinking", "thinking": "Considering."},
                },
                {"type": "text", "text": "Writing now."},
            ],
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act
        phase = self._entry()["phase"]

        # Assert
        self.assertEqual(phase["state"], "responding")

    def test_user_row_thinking_shaped_block_is_ignored(self):
        # Arrange
        self._add_trace_row(
            1,
            [
                {
                    "type": "thinking",
                    "data": {"type": "thinking", "thinking": "Not assistant data."},
                }
            ],
            AgentExecutionMessage.Provenance.MODEL,
            role="user",
        )

        # Act
        activity = self._entry()["activity"]

        # Assert
        self.assertEqual(activity, [])

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

    def test_selected_rfp_read_has_a_safe_label_and_source(self):
        # Arrange
        self._add_trace_row(
            1,
            [
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "read_selected_rfp",
                    "input": {},
                }
            ],
            AgentExecutionMessage.Provenance.MODEL,
        )
        self._add_trace_row(
            2,
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": {
                        "title": "Reproducibility RFP",
                        "url": "https://example.org/rfp",
                        "rfp_text": "Private full call text",
                    },
                }
            ],
            AgentExecutionMessage.Provenance.TOOL,
            role="user",
        )
        self._finish()

        # Act
        event = self._single_event()

        # Assert
        self.assertEqual(event["label"], "Read the selected RFP")
        self.assertEqual(
            event["sources"],
            [
                {
                    "title": "Reproducibility RFP",
                    "url": "https://example.org/rfp",
                }
            ],
        )
        self.assertNotIn("Private full call text", json.dumps(event, default=str))

    def test_live_turn_shows_its_newest_text_but_a_succeeded_turn_does_not(self):
        # Arrange: the only assistant text so far, which is either narration in
        # progress or the answer, depending on whether the run is over.
        self._add_trace_row(
            1,
            [{"type": "text", "text": "Let me look into that."}],
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act & Assert: while running it is the only way to see what was said...
        (narration,) = _narrations(self._entry()["activity"])
        self.assertEqual(narration["text"], "Let me look into that.")

        # ...and once the run succeeds the same text is the published answer,
        # so repeating it in the feed would show it twice.
        self._finish()
        self.assertEqual(_narrations(self._entry()["activity"]), [])

    def test_unsuccessful_turn_keeps_its_newest_text(self):
        # Arrange: text the model wrote on a turn that never got to publish
        # an answer.
        self._add_trace_row(
            1,
            [{"type": "text", "text": "Let me look into that."}],
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act & Assert: with no published message to repeat, the feed is the
        # only surviving account of what the model said.
        for status in (
            AgentExecution.Status.FAILED,
            AgentExecution.Status.INTERRUPTED,
            AgentExecution.Status.CANCELLED,
        ):
            with self.subTest(status=status):
                self._finish(status)
                (narration,) = _narrations(self._entry()["activity"])
                self.assertEqual(narration["text"], "Let me look into that.")

    def test_narration_survives_when_the_answers_trace_row_was_lost(self):
        # Arrange: a tool-calling row landed, but the answer's own trace write
        # failed (trace writes are best-effort), so the newest persisted
        # assistant row is mid-run narration. The run still succeeded and its
        # answer publishes from memory.
        self._add_trace_row(
            1,
            [
                {"type": "text", "text": "Let me read the note."},
                {"type": "tool_use", "id": "t1", "name": "read_note", "input": {}},
            ],
            AgentExecutionMessage.Provenance.MODEL,
        )
        self._add_trace_row(
            2,
            [{"type": "tool_result", "tool_use_id": "t1", "content": {"ok": True}}],
            AgentExecutionMessage.Provenance.TOOL,
            role="user",
        )
        self.execution.status = AgentExecution.Status.SUCCEEDED
        self.execution.publish_output_to_chat = True
        self.execution.final_output = {"text": "The note covers perovskites."}
        self.execution.save(
            update_fields=["status", "publish_output_to_chat", "final_output"]
        )

        # Act: the read repairs the missing publication, then renders.
        entry = self._entry()

        # Assert: the published answer does not contain this narration, so
        # suppressing it would erase words the chat never shows.
        self.assertEqual(
            list(
                self.conversation.chat_messages.filter(role="ASSISTANT").values_list(
                    "content", flat=True
                )
            ),
            ["The note covers perovskites."],
        )
        (narration,) = _narrations(entry["activity"])
        self.assertEqual(narration["text"], "Let me read the note.")

    def test_published_answer_split_across_final_row_blocks_is_not_echoed(self):
        # Arrange: a final row whose answer spans two text blocks; the chat
        # publishes their verbatim join, so each block is part of the answer.
        self._add_trace_row(
            1,
            [
                {"type": "text", "text": "Searching now. "},
                {"type": "text", "text": "Batteries improved."},
            ],
            AgentExecutionMessage.Provenance.MODEL,
        )
        self.execution.status = AgentExecution.Status.SUCCEEDED
        self.execution.publish_output_to_chat = True
        self.execution.final_output = {"text": "Searching now. Batteries improved."}
        self.execution.save(
            update_fields=["status", "publish_output_to_chat", "final_output"]
        )

        # Act & Assert: every block of the published answer stays out of the
        # feed even though no single block equals the published string.
        self.assertEqual(_narrations(self._entry()["activity"]), [])

    def test_succeeded_turn_stuck_on_publication_repair_keeps_its_text(self):
        # Arrange: a succeeded run whose answer publication failed and whose
        # on-read repair keeps failing, so the chat shows no assistant message.
        self._add_trace_row(
            1,
            [{"type": "text", "text": "Here is the answer."}],
            AgentExecutionMessage.Provenance.MODEL,
        )
        self.execution.status = AgentExecution.Status.SUCCEEDED
        self.execution.publish_output_to_chat = True
        self.execution.final_output = {"text": "Here is the answer."}
        self.execution.save(
            update_fields=["status", "publish_output_to_chat", "final_output"]
        )

        # Act: read while every repair attempt fails.
        with (
            patch.object(
                DatabaseAgentRecorder,
                "publish_assistant_output",
                side_effect=Exception("db down"),
            ),
            self.assertLogs(
                "research_ai.services.agent_persistence.chat_service", "WARNING"
            ),
        ):
            entry = self._entry()

        # Assert: until the answer actually lands as a chat message, the feed
        # still carries the model's text rather than showing nothing at all.
        self.assertTrue(entry["assistant_message_pending"])
        (narration,) = _narrations(entry["activity"])
        self.assertEqual(narration["text"], "Here is the answer.")

    def test_repair_landing_on_a_poll_reenters_the_live_scope(self):
        # Arrange: a succeeded turn whose publication kept failing until the
        # turn aged past the grace window and a newer attempt displaced it.
        # Neither age nor position can catch the repair; the publication
        # stamping the turn's heartbeat is what pulls it back into the window.
        self._add_trace_row(
            1,
            [{"type": "text", "text": "Here is the answer."}],
            AgentExecutionMessage.Provenance.MODEL,
        )
        self.execution.status = AgentExecution.Status.SUCCEEDED
        self.execution.publish_output_to_chat = True
        self.execution.final_output = {"text": "Here is the answer."}
        self.execution.save(
            update_fields=["status", "publish_output_to_chat", "final_output"]
        )
        _settle_beyond_grace(self.execution.id)
        AgentExecution.objects.create(
            conversation=self.conversation,
            attempt=2,
            status=AgentExecution.Status.SUCCEEDED,
        )

        # Act: the poll whose repair publishes the answer, then a poll after
        # the grace window has passed again.
        repairing = self.service.representation(
            self.conversation, activity_scope=ACTIVITY_LIVE
        )
        _settle_beyond_grace(self.execution.id)
        settled = self.service.representation(
            self.conversation, activity_scope=ACTIVITY_LIVE
        )

        # Assert: the repairing poll delivers the corrected feed -- the
        # narration moved into the chat -- and once the window passes the
        # turn drops back out of the projection.
        repaired_entry = repairing["executions"][0]
        self.assertFalse(repaired_entry["assistant_message_pending"])
        self.assertIn("activity", repaired_entry)
        self.assertEqual(_narrations(repaired_entry["activity"]), [])
        self.assertNotIn("activity", settled["executions"][0])

    def test_answer_published_by_another_request_reenters_the_live_scope(self):
        # Arrange: the same stuck turn, but the publication lands on a request
        # whose response carries no feed -- ``prepare_turn`` repairing before
        # the next question lands, or another tab's poll -- before this client
        # polls again.
        self._add_trace_row(
            1,
            [{"type": "text", "text": "Here is the answer."}],
            AgentExecutionMessage.Provenance.MODEL,
        )
        self.execution.status = AgentExecution.Status.SUCCEEDED
        self.execution.publish_output_to_chat = True
        self.execution.final_output = {"text": "Here is the answer."}
        self.execution.save(
            update_fields=["status", "publish_output_to_chat", "final_output"]
        )
        _settle_beyond_grace(self.execution.id)
        AgentExecution.objects.create(
            conversation=self.conversation,
            attempt=2,
            status=AgentExecution.Status.SUCCEEDED,
        )
        DatabaseAgentRecorder(self.execution).publish_assistant_output()

        # Act: a poll that performed no repair of its own.
        live = self.service.representation(
            self.conversation, activity_scope=ACTIVITY_LIVE
        )

        # Assert: the publication stamp pulled the turn back into the grace
        # window, so the corrected feed reaches every client polling within
        # it -- not only whichever request landed the message. Once the
        # window passes, the turn drops back out.
        entry = live["executions"][0]
        self.assertFalse(entry["assistant_message_pending"])
        self.assertIn("activity", entry)
        self.assertEqual(_narrations(entry["activity"]), [])
        _settle_beyond_grace(self.execution.id)
        later = self.service.representation(
            self.conversation, activity_scope=ACTIVITY_LIVE
        )
        self.assertNotIn("activity", later["executions"][0])

    def test_phase_names_the_open_tool_then_clears_when_terminal(self):
        # Arrange: a call whose result row has not landed.
        self._add_trace_row(
            1,
            [{"type": "tool_use", "id": "t1", "name": "read_note", "input": {}}],
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act & Assert
        phase = self._entry()["phase"]
        self.assertEqual(phase["state"], "using_tool")
        self.assertEqual(phase["label"], "Reading the note")
        self.assertEqual(phase["tool"], "read_note")

        self._finish(AgentExecution.Status.FAILED)
        self.assertIsNone(self._entry()["phase"])

    def test_phase_moves_on_when_a_lost_result_leaves_a_call_open(self):
        # Arrange: the call's result row was lost (trace writes are
        # best-effort) and the model has since spoken again -- proof the
        # dispatch finished, whatever its outcome was.
        self._add_trace_row(
            1,
            [{"type": "tool_use", "id": "t1", "name": "read_note", "input": {}}],
            AgentExecutionMessage.Provenance.MODEL,
        )
        self._add_trace_row(
            2,
            [{"type": "text", "text": "The note is long; summarizing."}],
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act
        entry = self._entry()

        # Assert: the phase reports the newer work, while the feed keeps the
        # call open rather than guessing an outcome for it.
        self.assertEqual(entry["phase"]["state"], "responding")
        (event,) = _tool_calls(entry["activity"])
        self.assertEqual(event["status"], "in_progress")

    def test_phase_names_the_current_call_despite_an_older_stale_one(self):
        # Arrange: an open call whose result row was lost, then a later turn
        # dispatching a single fresh call.
        self._add_trace_row(
            1,
            [{"type": "tool_use", "id": "t1", "name": "read_note", "input": {}}],
            AgentExecutionMessage.Provenance.MODEL,
        )
        self._add_trace_row(
            2,
            [
                {
                    "type": "tool_use",
                    "id": "t2",
                    "name": "web_search",
                    "input": {"query": "anything"},
                }
            ],
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act
        phase = self._entry()["phase"]

        # Assert: one call is genuinely current, so it is named rather than
        # hidden behind the generic batch label.
        self.assertEqual(phase["state"], "using_tool")
        self.assertEqual(phase["tool"], "web_search")
        self.assertEqual(phase["label"], "Searching the web")

    def test_phase_is_queued_until_a_worker_claims_the_turn(self):
        # Arrange: a submitted turn no worker has picked up; nothing is
        # thinking yet, and during a backlog this state can last a while.
        self.execution.status = AgentExecution.Status.PENDING
        self.execution.save(update_fields=["status"])

        # Act & Assert
        self.assertEqual(
            self._entry()["phase"],
            {"state": "queued", "label": "Waiting to start"},
        )

    def test_phase_stays_generic_while_a_batch_of_calls_is_open(self):
        # Arrange: one assistant turn dispatched two calls. They run in order
        # but their results land as one batch, so mid-batch the trace cannot
        # say which call is the current one.
        self._add_trace_row(
            1,
            [
                {"type": "tool_use", "id": "t1", "name": "read_note", "input": {}},
                {
                    "type": "tool_use",
                    "id": "t2",
                    "name": "web_search",
                    "input": {"query": "anything"},
                },
            ],
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act
        phase = self._entry()["phase"]

        # Assert: a tool phase that names no specific call.
        self.assertEqual(phase["state"], "using_tool")
        self.assertEqual(phase["label"], "Running tools")
        self.assertNotIn("tool", phase)

    def test_phase_is_thinking_once_the_tool_result_lands(self):
        # Arrange: the call completed and the model has not spoken since.
        self._add_trace_row(
            1,
            [{"type": "tool_use", "id": "t1", "name": "read_note", "input": {}}],
            AgentExecutionMessage.Provenance.MODEL,
        )
        self._add_trace_row(
            2,
            [{"type": "tool_result", "tool_use_id": "t1", "content": {"ok": True}}],
            AgentExecutionMessage.Provenance.TOOL,
            role="user",
        )

        # Act & Assert
        self.assertEqual(self._entry()["phase"]["state"], "thinking")

    def test_phase_is_responding_while_the_model_writes(self):
        # Arrange: a completed call, then prose.
        self._add_trace_row(
            1,
            [{"type": "tool_use", "id": "t1", "name": "read_note", "input": {}}],
            AgentExecutionMessage.Provenance.MODEL,
        )
        self._add_trace_row(
            2,
            [{"type": "tool_result", "tool_use_id": "t1", "content": {"ok": True}}],
            AgentExecutionMessage.Provenance.TOOL,
            role="user",
        )
        self._add_trace_row(
            3,
            [{"type": "text", "text": "Here is what the note says."}],
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act & Assert
        self.assertEqual(self._entry()["phase"]["state"], "responding")

    def test_truncated_trace_marker_is_not_shown_as_narration(self):
        # Arrange: the marker a row too large to persist leaves behind, which is
        # written for an operator reading the trace.
        self._add_trace_row(
            1,
            [
                {
                    "type": "text",
                    "text": "[Trace message omitted because it exceeded the "
                    "durable row limit.]",
                    "_truncated": True,
                    "omitted_blocks": 3,
                }
            ],
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act & Assert
        self.assertEqual(self._entry()["activity"], [])

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
        chats_url = f"/api/research_ai/notebook/notes/{self.note.id}/chats/"
        self.client.force_authenticate(self.owner)
        created = self.client.post(chats_url, {}, format="json")
        self.chat_url = f"{chats_url}{created.data['conversation_id']}/"

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
        self.assertEqual(before.data["executions"][0]["phase"]["state"], "queued")

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
        (event,) = _tool_calls(execution["activity"])
        self.assertEqual(event["tool"], "read_note")
        self.assertEqual(event["label"], "Read the note")
        self.assertEqual(event["status"], "succeeded")

    def test_get_chat_surfaces_thinking_events(self):
        # Arrange
        with patch("research_ai.tasks.run_notebook_chat_turn_task.delay"):
            posted = self.client.post(
                f"{self.chat_url}messages/",
                {"message": "Summarize the note"},
                format="json",
            )
        _make_service(
            provider=FakeProvider(
                [
                    tool_turn(
                        "t1",
                        "read_note",
                        {"note_id": self.note.id},
                        thinking={
                            "type": "thinking",
                            "thinking": "I should read the note first.",
                            "signature": "sig-opaque",
                        },
                    ),
                    text_turn("Summary."),
                ]
            )
        ).run_turn(posted.data["execution_id"])

        # Act
        response = self.client.get(self.chat_url)

        # Assert
        (execution,) = response.data["executions"]
        (thinking,) = _thinkings(execution["activity"])
        self.assertEqual(thinking["text"], "I should read the note first.")
        self.assertNotIn("sig-opaque", json.dumps(response.data, default=str))

    def test_activity_live_query_param_selects_the_polling_projection(self):
        # Arrange: two finished turns, the older settled beyond the grace
        # window, so it is the one a poll no longer recomputes.
        self.client.force_authenticate(self.owner)
        execution_ids = []
        for text, call_id in (("First", "t1"), ("Second", "t2")):
            with patch("research_ai.tasks.run_notebook_chat_turn_task.delay"):
                posted = self.client.post(
                    f"{self.chat_url}messages/", {"message": text}, format="json"
                )
            execution_ids.append(posted.data["execution_id"])
            _make_service(
                provider=FakeProvider(
                    [
                        tool_turn(call_id, "read_note", {"note_id": self.note.id}),
                        text_turn("Done."),
                    ]
                )
            ).run_turn(posted.data["execution_id"])
        _settle_beyond_grace(execution_ids[0])

        # Act
        full = self.client.get(self.chat_url)
        live = self.client.get(self.chat_url, {"activity": "live"})

        # Assert: the settled turn keeps its feed on a full read and loses the
        # key on a poll; the newest turn carries its feed either way.
        self.assertTrue(all("activity" in e for e in full.data["executions"]))
        older, newest = live.data["executions"]
        self.assertNotIn("activity", older)
        self.assertEqual(len(_tool_calls(newest["activity"])), 1)

    def test_unknown_activity_scope_falls_back_to_the_full_projection(self):
        # Arrange: a stale or mistyped client parameter must cost performance,
        # not correctness.
        self.client.force_authenticate(self.owner)
        with patch("research_ai.tasks.run_notebook_chat_turn_task.delay"):
            posted = self.client.post(
                f"{self.chat_url}messages/", {"message": "Summarize"}, format="json"
            )
        _make_service(
            provider=FakeProvider(
                [
                    tool_turn("t1", "read_note", {"note_id": self.note.id}),
                    text_turn("Done."),
                ]
            )
        ).run_turn(posted.data["execution_id"])

        # Act
        response = self.client.get(self.chat_url, {"activity": "nonsense"})

        # Assert
        (execution,) = response.data["executions"]
        self.assertEqual(len(_tool_calls(execution["activity"])), 1)
