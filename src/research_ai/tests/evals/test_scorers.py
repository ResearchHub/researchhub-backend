from unittest import TestCase

from research_ai.evals.cases import NOTEBOOK, EvalCase, Expectations
from research_ai.evals.harness import CaseRun, NoteSnapshot, ToolCall, TurnRun
from research_ai.evals.scorers import (
    edit_scope,
    grounded_citations,
    link_format,
    proposal_hygiene,
    reply_shape,
    sections,
    tool_expectations,
    turn_ok,
)
from research_ai.models import AgentExecution

NOTE_ID = 7


def _heading(text, level=2):
    return {"type": "heading", "attrs": {"level": level}, "content": [text]}


def _link(text, href):
    return {
        "type": "paragraph",
        "content": [
            {
                "type": "text",
                "text": text,
                "marks": [{"type": "link", "attrs": {"href": href}}],
            }
        ],
    }


def _case(**expect):
    return EvalCase(
        id="notebook/x",
        agent=NOTEBOOK,
        turns=["Do it."],
        expect=Expectations(**expect),
    )


def _note(blocks, plain_text="", document_type="NOTE"):
    return NoteSnapshot(
        id=NOTE_ID,
        title="T",
        document_type=document_type,
        blocks=blocks,
        plain_text=plain_text,
    )


def _turn(reply="Done.", status=AgentExecution.Status.SUCCEEDED, calls=()):
    return TurnRun(
        index=0,
        message="Do it.",
        execution_id=1,
        status=status,
        error="",
        reply=reply,
        iterations=1,
        input_tokens=0,
        output_tokens=0,
        cost_microusd=0,
        duration_ms=None,
        tool_calls=list(calls),
    )


def _call(name, result="", is_error=False, **tool_input):
    return ToolCall(
        turn=0, name=name, input=tool_input, result=result, is_error=is_error
    )


def _run(before=None, after=None, turns=None, error=""):
    return CaseRun(
        case_id="notebook/x",
        agent=NOTEBOOK,
        model="m",
        trial=0,
        turns=[_turn()] if turns is None else turns,
        notes_before={} if before is None else {NOTE_ID: before},
        notes_after={} if after is None else {NOTE_ID: after},
        error=error,
    )


class SectionsTests(TestCase):
    def test_groups_blocks_under_headings_including_subsections(self):
        # Arrange
        blocks = [
            "lead",
            _heading("A"),
            "a1",
            _heading("A.1", 3),
            "a2",
            _heading("B"),
            "b1",
        ]

        # Act
        result = sections(blocks)

        # Assert
        self.assertEqual(result[""], ["lead"])
        self.assertEqual(result["A"], ["a1", _heading("A.1", 3), "a2"])
        self.assertEqual(result["A.1"], ["a2"])
        self.assertEqual(result["B"], ["b1"])


class TurnOkTests(TestCase):
    def test_fails_on_a_failed_turn(self):
        # Act
        score = turn_ok(
            _case(), _run(turns=[_turn(status=AgentExecution.Status.FAILED)])
        )

        # Assert
        self.assertEqual(score.value, 0.0)

    def test_fails_on_a_crashed_run(self):
        # Act
        score = turn_ok(_case(), _run(turns=[], error="ValueError: boom"))

        # Assert
        self.assertEqual(score.value, 0.0)
        self.assertIn("ValueError: boom", score.details)

    def test_passes_when_every_turn_succeeded(self):
        # Act / Assert
        self.assertEqual(turn_ok(_case(), _run()).value, 1.0)


class ToolExpectationsTests(TestCase):
    def test_scores_missing_and_forbidden_tools(self):
        # Arrange
        run = _run(
            before=_note([]),
            turns=[
                _turn(calls=[_call("read_note", note_id=NOTE_ID), _call("create_note")])
            ],
        )
        case = _case(
            tools_called=["read_note", "edit_note"], tools_not_called=["create_note"]
        )

        # Act
        score = tool_expectations(case, run)

        # Assert
        self.assertEqual(
            score.details, ["never called edit_note", "called create_note"]
        )
        self.assertAlmostEqual(score.value, 0.5)

    def test_a_required_tool_that_only_failed_does_not_count(self):
        # Arrange
        run = _run(
            before=_note([]),
            turns=[
                _turn(
                    calls=[
                        _call("read_note", note_id=NOTE_ID),
                        _call("edit_note", is_error=True, note_id=NOTE_ID),
                    ]
                )
            ],
        )

        # Act
        score = tool_expectations(_case(tools_called=["edit_note"]), run)

        # Assert
        self.assertEqual(score.details, ["every edit_note call failed"])

    def test_counts_a_native_provider_tool_call(self):
        # Arrange
        native = ToolCall(
            turn=0,
            name="web_search",
            input={},
            result="[]",
            is_error=False,
            native=True,
        )
        run = _run(turns=[_turn(calls=[native])])

        # Act
        score = tool_expectations(_case(tools_not_called=["web_search"]), run)

        # Assert
        self.assertEqual(score.details, ["called web_search"])

    def test_a_forbidden_tool_counts_even_when_it_failed(self):
        # Arrange
        run = _run(turns=[_turn(calls=[_call("create_note", is_error=True)])])

        # Act
        score = tool_expectations(_case(tools_not_called=["create_note"]), run)

        # Assert
        self.assertEqual(score.details, ["called create_note"])

    def test_flags_an_edit_of_a_fixture_note_before_reading_it(self):
        # Arrange
        run = _run(
            before=_note([]),
            turns=[_turn(calls=[_call("edit_note", note_id=str(NOTE_ID))])],
        )

        # Act
        score = tool_expectations(_case(), run)

        # Assert
        self.assertEqual(
            score.details, [f"edit_note on note {NOTE_ID} before reading it"]
        )

    def test_a_note_the_agent_created_needs_no_read(self):
        # Arrange
        run = _run(turns=[_turn(calls=[_call("edit_note", note_id=99)])])

        # Act / Assert
        self.assertEqual(tool_expectations(_case(), run).value, 1.0)


class EditScopeTests(TestCase):
    def test_flags_only_the_protected_section_that_changed(self):
        # Arrange
        before = _note([_heading("Intro"), "keep", _heading("Methods"), "old"])
        after = _note([_heading("Intro"), "changed", _heading("Methods"), "new"])

        # Act
        score = edit_scope(_case(unchanged_sections=["Intro"]), _run(before, after))

        # Assert
        self.assertEqual(score.value, 0.0)
        self.assertEqual(score.details, ["section 'Intro' changed"])

    def test_passes_when_only_unprotected_sections_changed(self):
        # Arrange
        before = _note([_heading("Intro"), "keep", _heading("Methods"), "old"])
        after = _note([_heading("Intro"), "keep", _heading("Methods"), "new"])

        # Act / Assert
        self.assertEqual(
            edit_scope(_case(unchanged_sections=["Intro"]), _run(before, after)).value,
            1.0,
        )

    def test_note_unchanged_catches_any_edit(self):
        # Act
        score = edit_scope(_case(note_unchanged=True), _run(_note(["a"]), _note(["b"])))

        # Assert
        self.assertEqual(score.value, 0.0)

    def test_not_applicable_without_expectations(self):
        # Act / Assert
        self.assertIsNone(edit_scope(_case(), _run(_note(["a"]), _note(["b"]))))


class GroundedCitationsTests(TestCase):
    def test_flags_a_doi_no_tool_returned(self):
        # Arrange
        after = _note(
            [_link("Smith 2024", "https://doi.org/10.1234/real.5"), "10.9999/made.up"]
        )
        run = _run(
            before=_note([]),
            after=after,
            turns=[
                _turn(calls=[_call("search_works", result='{"doi": "10.1234/REAL.5"}')])
            ],
        )

        # Act
        score = grounded_citations(_case(), run)

        # Assert
        self.assertEqual(score.details, ["ungrounded DOI 10.9999/made.up"])
        self.assertAlmostEqual(score.value, 0.5)

    def test_a_note_read_back_does_not_ground_what_the_agent_wrote(self):
        # Arrange
        after = _note(["10.9999/made.up"])
        run = _run(
            before=_note([]),
            after=after,
            turns=[
                _turn(
                    calls=[
                        _call("edit_note", result='{"saved": true}'),
                        _call("read_note", result='{"blocks": ["10.9999/made.up"]}'),
                    ]
                )
            ],
        )

        # Act
        score = grounded_citations(_case(), run)

        # Assert
        self.assertEqual(score.details, ["ungrounded DOI 10.9999/made.up"])

    def test_a_search_query_echoed_in_its_result_is_not_evidence(self):
        # Arrange
        run = _run(
            before=_note([]),
            after=_note(["10.9999/made.up"]),
            turns=[
                _turn(
                    calls=[
                        _call(
                            "web_search",
                            result='{"query": "10.9999/made.up", "results": []}',
                            query="10.9999/made.up",
                        ),
                    ]
                )
            ],
        )

        # Act
        score = grounded_citations(_case(), run)

        # Assert
        self.assertEqual(score.details, ["ungrounded DOI 10.9999/made.up"])

    def test_a_search_result_that_carries_the_doi_grounds_it(self):
        # Arrange
        result = (
            '{"query": "spindles", "results": [{"url": "https://doi.org/10.1234/a.1"}]}'
        )
        run = _run(
            before=_note([]),
            after=_note(["10.1234/a.1"]),
            turns=[_turn(calls=[_call("web_search", result=result, query="spindles")])],
        )

        # Act / Assert
        self.assertEqual(grounded_citations(_case(), run).value, 1.0)

    def test_not_applicable_without_dois(self):
        # Act / Assert
        self.assertIsNone(grounded_citations(_case(), _run(_note([]), _note(["x"]))))


class LinkFormatTests(TestCase):
    def test_flags_new_markdown_links_and_bare_urls(self):
        # Arrange
        after = _note(
            [
                "See [Smith](https://example.org/a).",
                "Also https://example.org/b",
                _link("ok", "https://example.org/c"),
            ]
        )

        # Act
        score = link_format(_case(), _run(_note([]), after))

        # Assert
        self.assertEqual(score.value, 0.0)
        self.assertEqual(len(score.details), 2)

    def test_ignores_problems_already_in_the_fixture(self):
        # Arrange
        blocks = ["Also https://example.org/b"]

        # Act / Assert
        self.assertEqual(
            link_format(_case(), _run(_note(blocks), _note(blocks))).value, 1.0
        )


class ProposalHygieneTests(TestCase):
    def test_flags_deferrals_added_to_a_proposal(self):
        # Arrange
        after = _note(
            [], "The sample size remains to be determined.", "PREREGISTRATION"
        )

        # Act
        score = proposal_hygiene(_case(), _run(_note([], "", "PREREGISTRATION"), after))

        # Assert
        self.assertEqual(score.value, 0.0)

    def test_not_applicable_to_plain_notes(self):
        # Arrange
        after = _note([], "Thresholds remain to be set.")

        # Act / Assert
        self.assertIsNone(proposal_hygiene(_case(), _run(_note([]), after)))


class ReplyShapeTests(TestCase):
    def test_flags_a_missing_reply(self):
        # Act
        score = reply_shape(_case(), _run(turns=[_turn(reply="")]))

        # Assert
        self.assertEqual(score.details, ["turn 0: no reply"])

    def test_flags_a_reply_that_pastes_the_note(self):
        # Arrange
        paragraphs = [f"{i} " + "x" * 130 for i in range(3)]
        after = _note([], "\n".join(paragraphs))

        # Act
        score = reply_shape(
            _case(), _run(_note([]), after, [_turn(reply=" ".join(paragraphs))])
        )

        # Assert
        self.assertEqual(score.details, ["turn 0: pastes 3 note paragraphs"])
