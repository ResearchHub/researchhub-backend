import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from research_ai.models import AgentExecutionMessage
from research_ai.services.agent_persistence.activity import conversation_activity_events
from research_ai.services.notebook_chat.activity import execution_phase, public_activity
from research_ai.services.notebook_chat.code_execution import (
    MAX_CODE_CHARS,
    MAX_OUTPUT_CHARS,
)


class CodeExecutionActivityTests(SimpleTestCase):
    def _events(self, result=None, *, tool="code_execution", code="print(42)"):
        code_field = "command" if tool == "bash_code_execution" else "code"
        content = [
            {
                "type": "server_tool",
                "data": {
                    "type": "server_tool_use",
                    "id": "s1",
                    "name": tool,
                    "input": {code_field: code, "private": "input-sentinel"},
                },
            }
        ]
        if result is not None:
            content.append(
                {
                    "type": "server_tool",
                    "data": {
                        "type": f"{tool}_tool_result",
                        "tool_use_id": "s1",
                        "content": result,
                    },
                }
            )
        with patch.object(AgentExecutionMessage.objects, "filter") as query:
            rows = query.return_value.exclude.return_value.order_by.return_value
            rows.values_list.return_value = [(1, "assistant", content, timezone.now())]
            return conversation_activity_events(Mock())[1]

    def _public(self, events, *, active=False):
        return public_activity(
            events,
            execution_active=active,
            answer_published=False,
            published_answer=None,
        )[0]

    def test_readable_result_exposes_code_output_and_summary(self):
        # Arrange
        events = self._events(
            {
                "type": "code_execution_result",
                "return_code": 0,
                "stdout": "42\n",
                "stderr": "private-error-sentinel",
                "content": [{"file_id": "private-file-sentinel"}],
            }
        )

        # Act
        event = self._public(events)

        # Assert
        self.assertEqual(event["label"], "Code finished")
        self.assertEqual(event["status"], "succeeded")
        self.assertEqual(
            event["code_execution"],
            {
                "code": "print(42)",
                "code_truncated": False,
                "return_code": 0,
                "output": "42\n",
                "output_truncated": False,
                "output_count": 1,
            },
        )
        self.assertEqual(
            event["detail"], "Code finished successfully. Produced 1 output item."
        )
        self.assertNotIn("sentinel", json.dumps(event, default=str))

    def test_encrypted_output_is_never_exposed(self):
        # Arrange
        events = self._events(
            {
                "type": "encrypted_code_execution_result",
                "return_code": 0,
                "encrypted_stdout": "encrypted-sentinel",
                "stdout": "unexpected-sentinel",
                "content": [],
            }
        )

        # Act
        event = self._public(events)

        # Assert
        self.assertEqual(event["detail"], "Code finished successfully.")
        self.assertNotIn("output", event["code_execution"])
        self.assertNotIn("sentinel", json.dumps(event, default=str))

    def test_nonzero_exit_codes_fail_for_python_and_shell(self):
        for tool in ("code_execution", "bash_code_execution"):
            with self.subTest(tool=tool):
                # Arrange
                events = self._events(
                    {"return_code": 1, "stderr": "private-sentinel"}, tool=tool
                )

                # Act
                event = self._public(events)

                # Assert
                self.assertEqual(event["status"], "failed")
                self.assertEqual(event["label"], "Code execution failed")
                self.assertEqual(
                    event["detail"], "Code exited with error (exit code 1)."
                )
                self.assertEqual(event["code_execution"]["return_code"], 1)
                self.assertNotIn("sentinel", json.dumps(event, default=str))

    def test_provider_errors_have_public_explanations(self):
        cases = (
            ("execution_time_exceeded", "Execution timed out."),
            ("unknown-private-sentinel", "Code execution failed."),
        )
        for error_code, summary in cases:
            with self.subTest(error_code=error_code):
                # Arrange
                events = self._events(
                    {
                        "type": "code_execution_tool_result_error",
                        "error_code": error_code,
                    }
                )

                # Act
                event = self._public(events)

                # Assert
                self.assertEqual(event["status"], "failed")
                self.assertEqual(event["detail"], summary)
                self.assertNotIn("sentinel", json.dumps(event, default=str))

    def test_running_and_interrupted_calls_do_not_claim_completion(self):
        # Arrange
        events = self._events()

        # Act
        running = self._public(events, active=True)
        interrupted = self._public(events)
        phase = execution_phase(events, execution_active=True, execution_claimed=True)

        # Assert
        self.assertEqual(running["label"], "Running code")
        self.assertEqual(running["status"], "in_progress")
        self.assertEqual(running["code_execution"]["code"], "print(42)")
        self.assertNotIn("detail", running)
        self.assertEqual(interrupted["label"], "Code execution interrupted")
        self.assertEqual(interrupted["status"], "interrupted")
        self.assertEqual(phase["label"], "Running code")

    def test_code_and_output_are_bounded_and_marked_when_truncated(self):
        # Arrange
        events = self._events(
            {"return_code": 0, "stdout": "y" * (MAX_OUTPUT_CHARS + 1)},
            code="x" * (MAX_CODE_CHARS + 1),
        )

        # Act
        details = self._public(events)["code_execution"]

        # Assert
        self.assertEqual(len(details["code"]), MAX_CODE_CHARS)
        self.assertTrue(details["code_truncated"])
        self.assertEqual(len(details["output"]), MAX_OUTPUT_CHARS)
        self.assertTrue(details["output_truncated"])

    def test_shell_command_is_available_as_code(self):
        # Arrange
        events = self._events(tool="bash_code_execution", code="echo hello")

        # Act
        event = self._public(events, active=True)

        # Assert
        self.assertEqual(event["code_execution"]["code"], "echo hello")

    def test_missing_or_malformed_fields_are_not_invented(self):
        for result in ({}, {"return_code": True, "stdout": {}, "content": "bad"}):
            with self.subTest(result=result):
                # Arrange
                events = self._events(result, code=None)

                # Act
                event = self._public(events)

                # Assert
                self.assertNotIn("code_execution", event)
                self.assertNotIn("detail", event)

    def test_other_tools_keep_their_existing_projection(self):
        # Arrange: a return_code field on an unrelated tool has no execution
        # semantics, and its inputs and output must not gain a code preview.
        events = self._events(
            {"return_code": 1, "stdout": "private-sentinel"}, tool="web_search"
        )

        # Act
        event = self._public(events)

        # Assert
        self.assertEqual(event["label"], "Searched the web")
        self.assertEqual(event["status"], "succeeded")
        self.assertNotIn("code_execution", event)
        self.assertNotIn("sentinel", json.dumps(event, default=str))
