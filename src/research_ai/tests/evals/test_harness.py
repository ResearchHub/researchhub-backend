import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from django.test import TestCase, override_settings

from note.related_models.note_model import Note
from research_ai.evals.cases import parse_case
from research_ai.evals.harness import AgentEvalHarness, build_engine
from research_ai.evals.report import (
    ScoredRun,
    build_report,
    format_summary,
    write_report,
)
from research_ai.evals.scorers import score_run
from research_ai.models import AgentExecution
from research_ai.tests.agent.persistence_test_helpers import (
    FakeProvider,
    text_turn,
    tool_turn,
)

MODEL_SETTINGS = {
    "ANTHROPIC_AWS_WORKSPACE_ID": "ws-test",
    "AWS_REGION_NAME": "us-east-1",
    "OPENROUTER_API_KEY": "or-test",
}

NOTEBOOK_CASE = {
    "id": "notebook/rewrite-methods",
    "agent": "notebook",
    "note": {
        "title": "Study",
        "document_type": "PREREGISTRATION",
        "blocks": ["## Intro", "Keep this.", "## Methods", "Old methods."],
    },
    "turns": ["Rewrite the methods."],
    "expect": {
        "tools_called": ["read_note", "edit_note"],
        "unchanged_sections": ["Intro"],
    },
}

ASSISTANT_CASE = {
    "id": "assistant/start-and-revise",
    "agent": "assistant",
    "turns": ["Start a proposal.", "Thanks."],
    "expect": {"tools_called": ["create_note", "edit_note"]},
}


class ScriptedProvider(FakeProvider):
    """A ``FakeProvider`` whose turns may be built when they are reached, for
    tool inputs that name rows the harness has not created yet."""

    def complete(self, **kwargs):
        if callable(self.turns[0]):
            self.turns[0] = self.turns[0]()
        return super().complete(**kwargs)


def _latest_note():
    return Note.objects.order_by("-id").first()


def _harness(provider, **kwargs):
    return AgentEvalHarness(
        engine_factory=lambda workflow: build_engine(
            workflow,
            provider=provider,
            oa_client=Mock(),
            web_search_client=Mock(configured=False),
        ),
        **kwargs,
    )


@override_settings(**MODEL_SETTINGS)
class AgentEvalHarnessTests(TestCase):
    def test_runs_a_notebook_case_through_the_chat_engine(self):
        # Arrange
        case = parse_case(NOTEBOOK_CASE)
        provider = ScriptedProvider(
            [
                lambda: tool_turn("t1", "read_note", {"note_id": _latest_note().id}),
                lambda: tool_turn(
                    "t2",
                    "edit_note",
                    {
                        "note_id": _latest_note().id,
                        "expected_version_id": _latest_note().latest_version.id,
                        "edits": [
                            {"op": "replace", "from": 3, "to": 3, "blocks": ["New."]}
                        ],
                    },
                ),
                text_turn("I rewrote the methods."),
            ]
        )

        # Act
        run = _harness(provider).run(case)

        # Assert
        self.assertEqual(run.error, "")
        self.assertEqual(len(run.turns), 1)
        turn = run.turns[0]
        self.assertEqual(turn.status, AgentExecution.Status.SUCCEEDED)
        self.assertEqual(turn.reply, "I rewrote the methods.")
        self.assertEqual(
            [call.name for call in turn.tool_calls], ["read_note", "edit_note"]
        )
        self.assertIn("Keep this.", turn.tool_calls[0].result)
        (note_id,) = run.notes_after
        self.assertIn("Old methods.", run.notes_before[note_id].plain_text)
        self.assertIn("New.", run.notes_after[note_id].plain_text)
        self.assertNotIn("Old methods.", run.notes_after[note_id].plain_text)
        scores = {score.name: score.value for score in score_run(case, run)}
        self.assertEqual(scores["turn_ok"], 1.0)
        self.assertEqual(scores["tool_expectations"], 1.0)
        self.assertEqual(scores["edit_scope"], 1.0)

    def test_runs_a_multi_turn_assistant_case_on_the_notes_it_creates(self):
        # Arrange
        case = parse_case(ASSISTANT_CASE)
        provider = ScriptedProvider(
            [
                tool_turn(
                    "c1",
                    "create_note",
                    {"title": "Plan", "document_type": "PREREGISTRATION"},
                ),
                lambda: tool_turn(
                    "e1",
                    "edit_note",
                    {
                        "note_id": _latest_note().id,
                        "expected_version_id": None,
                        "edits": [{"op": "insert", "at": 0, "blocks": ["Aims."]}],
                    },
                ),
                text_turn("I drafted it."),
                text_turn("You're welcome."),
            ]
        )

        # Act
        run = _harness(provider).run(case)

        # Assert
        self.assertEqual(run.error, "")
        self.assertEqual(
            [turn.reply for turn in run.turns], ["I drafted it.", "You're welcome."]
        )
        self.assertEqual(run.notes_before, {})
        (note,) = run.notes_after.values()
        self.assertEqual(note.title, "Plan")
        self.assertIn("Aims.", note.plain_text)
        scores = {score.name: score.value for score in score_run(case, run)}
        self.assertEqual(scores["tool_expectations"], 1.0)
        self.assertEqual(scores["reply_shape"], 1.0)

    def test_records_a_crash_outside_the_turns_instead_of_raising(self):
        # Arrange
        case = parse_case(NOTEBOOK_CASE)

        # Act
        run = _harness(FakeProvider([]), model_ref="nope:not-a-model").run(case)

        # Assert
        self.assertIn("ValueError", run.error)
        self.assertEqual(run.turns, [])
        scores = score_run(case, run)
        self.assertEqual(
            [(score.name, score.value) for score in scores], [("turn_ok", 0.0)]
        )

    def test_report_round_trips_a_scored_run(self):
        # Arrange
        case = parse_case(ASSISTANT_CASE)
        provider = ScriptedProvider([text_turn("Hello."), text_turn("Bye.")])
        run = _harness(provider).run(case)
        results = [ScoredRun(case, run, score_run(case, run))]

        # Act
        report = build_report(
            results, model="m", tag="t", started_at=datetime(2026, 1, 1)
        )
        with tempfile.TemporaryDirectory() as out:
            path = write_report(report, Path(out))
            written = json.loads(path.read_text())
        summary = format_summary(report)

        # Assert
        self.assertEqual(written["summary"]["runs"], 1)
        self.assertEqual(written["runs"][0]["case_id"], case.id)
        # create_note and edit_note never called; the read-before-edit rule held.
        self.assertEqual(report["summary"]["by_scorer"]["tool_expectations"], 0.333)
        self.assertIn(case.id, summary)
        self.assertIn("never called create_note", summary)
