from unittest import TestCase
from unittest.mock import Mock

from research_ai.services.agent.tools import Tool, Toolset
from research_ai.services.agent.types import AssistantTurn, StopReason, ToolUseBlock
from research_ai.services.question_tool_service import build_question_tool
from research_ai.tests.agent.test_loop import (
    FakeProvider,
    _build_agent,
    _build_text_turn,
    _build_tool_turn,
)


class QuestionToolTests(TestCase):
    def test_question_ends_run_without_an_extra_model_call(self):
        # Arrange
        provider = FakeProvider(
            [
                _build_tool_turn(
                    "q1",
                    "ask_question",
                    {
                        "question": " Which audience? ",
                        "options": ["Researchers", "Public"],
                    },
                ),
            ]
        )
        agent = _build_agent(provider, Toolset([build_question_tool()]))

        # Act
        result = agent.run("Rewrite this.")

        # Assert
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result.stop_reason, "user_input")
        self.assertEqual(result.final_text, "Which audience?\n- Researchers\n- Public")
        self.assertEqual(result.user_input_request.question, "Which audience?")
        self.assertEqual(result.messages[-1].content[0].tool_use_id, "q1")
        self.assertFalse(result.messages[-1].content[0].is_error)

    def test_invalid_questions_do_not_stop_the_run(self):
        # Arrange
        toolset = Toolset([build_question_tool()])
        invalid = [
            {},
            {"question": " "},
            {"question": 12},
            {"question": "x" * 2001},
            {"question": "Q?", "options": "yes"},
            {"question": "Q?", "options": ["yes"]},
            {"question": "Q?", "options": ["yes", " YES "]},
            {"question": "Q?", "options": ["yes", " "]},
            {"question": "Q?", "options": ["yes", 3]},
            {"question": "Q?", "options": ["yes", "x" * 201]},
            {"question": "Q?", "options": list("abcdef")},
            {"question": "Q?", "unknown": True},
        ]
        for args in invalid:
            with self.subTest(args=args):
                # Act
                result, stop = toolset.dispatch("ask_question", args)

                # Assert
                self.assertIn("error", result)
                self.assertFalse(stop)

    def test_invalid_question_can_be_corrected(self):
        # Arrange
        provider = FakeProvider(
            [
                _build_tool_turn("bad", "ask_question", {"question": ""}),
                _build_tool_turn(
                    "good", "ask_question", {"question": "What is the deadline?"}
                ),
            ]
        )

        # Act
        result = _build_agent(provider, Toolset([build_question_tool()])).run(
            "Draft it."
        )

        # Assert
        self.assertEqual(result.user_input_request.options, [])
        self.assertEqual(result.iterations, 2)
        self.assertTrue(provider.calls[1][-1].content[0].is_error)

    def test_mixed_question_and_write_batch_executes_neither_in_either_order(self):
        for question_first in (True, False):
            with self.subTest(question_first=question_first):
                # Arrange
                write = Mock(return_value={"saved": True})
                calls = [
                    ToolUseBlock("q", "ask_question", {"question": "Which section?"}),
                    ToolUseBlock("w", "edit_note", {}),
                ]
                if not question_first:
                    calls.reverse()
                provider = FakeProvider(
                    [
                        AssistantTurn([], calls, StopReason.TOOL_USE),
                        _build_tool_turn(
                            "retry", "ask_question", {"question": "Which section?"}
                        ),
                    ]
                )
                tools = Toolset(
                    [build_question_tool(), Tool("edit_note", "edit", {}, write)]
                )

                # Act
                result = _build_agent(provider, tools).run("Update the note.")

                # Assert
                write.assert_not_called()
                errors = provider.calls[1][-1].content
                self.assertEqual({block.tool_use_id for block in errors}, {"q", "w"})
                self.assertTrue(all(block.is_error for block in errors))
                self.assertEqual(result.stop_reason, "user_input")

    def test_next_human_message_continues_with_question_context(self):
        # Arrange
        provider = FakeProvider(
            [
                _build_tool_turn("q", "ask_question", {"question": "Which audience?"}),
                _build_text_turn("I will write for first-year students."),
            ]
        )
        agent = _build_agent(provider, Toolset([build_question_tool()]))
        first = agent.run("Rewrite this.")

        # Act
        second = agent.continue_conversation(first.messages, "First-year students")

        # Assert
        self.assertEqual(provider.calls[1][-1].content[0].text, "First-year students")
        self.assertEqual(
            provider.calls[1][-2].content[0].content["question"], "Which audience?"
        )
        self.assertEqual(second.stop_reason, "end_turn")
        self.assertIsNone(second.user_input_request)
