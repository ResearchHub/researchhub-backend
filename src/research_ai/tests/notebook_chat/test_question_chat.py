from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from rest_framework.test import APITestCase

from note.tests.helpers import create_note
from research_ai.models import AgentExecution
from research_ai.services.agent.types import ToolResultBlock
from research_ai.services.agent_persistence import DatabaseAgentRecorder
from research_ai.services.notebook_chat import NotebookChatService
from research_ai.tests.agent.persistence_test_helpers import (
    FakeProvider,
    text_turn,
    tool_turn,
)
from researchhub_access_group.constants import ADMIN
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument


@override_settings(
    ANTHROPIC_AWS_WORKSPACE_ID="ws-test",
    AWS_REGION_NAME="us-east-1",
    OPENROUTER_API_KEY="or-test",
)
class QuestionChatTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="questions@researchhub_test.com",
            email="questions@researchhub_test.com",
            password="password",
            is_staff=True,
        )
        note, _ = create_note(self.user, organization=None)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=note.unified_document.id,
            user=self.user,
        )
        self.chat_urls = [
            "/api/research_ai/assistant/chats/",
            f"/api/research_ai/notebook/notes/{note.id}/chats/",
        ]
        self.client.force_authenticate(self.user)
        self.question = {
            "question": "Who is the audience?",
            "options": ["Researchers", "Public"],
        }

    def _create_chat(self, base_url):
        response = self.client.post(base_url, {}, format="json")
        self.assertEqual(response.status_code, 201)
        return f"{base_url}{response.data['conversation_id']}/"

    def _post(self, url, message="Rewrite this", **extra):
        with patch("research_ai.tasks.run_notebook_chat_turn_task.delay"):
            return self.client.post(
                f"{url}messages/", {"message": message, **extra}, format="json"
            )

    def _ask(self, url):
        response = self._post(url)
        self.assertEqual(response.status_code, 202)
        execution = AgentExecution.objects.get(id=response.data["execution_id"])
        self._run(execution, [tool_turn("question", "ask_question", self.question)])
        return execution

    def _run(self, execution, turns):
        provider = FakeProvider(turns)
        NotebookChatService(
            provider=provider,
            oa_client=Mock(),
            web_search_client=Mock(configured=False),
            event_publisher=Mock(),
        ).run_turn(execution.id)
        execution.refresh_from_db()
        return provider

    def test_question_survives_trace_loss_and_free_text_answer_continues_both_chats(
        self,
    ):
        for base_url in self.chat_urls:
            with self.subTest(base_url=base_url):
                # Arrange
                url = self._create_chat(base_url)
                execution = self._ask(url)
                execution.messages.all().delete()

                # Act
                detail = self.client.get(url).data
                answer = self._post(
                    url, "First-year students", question_execution_id=execution.id
                )

                # Assert
                self.assertEqual(execution.status, AgentExecution.Status.SUCCEEDED)
                self.assertEqual(execution.stop_reason, "user_input")
                self.assertIsNone(execution.usage_reservation_expires_at)
                self.assertEqual(
                    detail["pending_question"],
                    {"execution_id": execution.id, **self.question},
                )
                self.assertEqual(detail["executions"][-1]["question"], self.question)
                self.assertIn("Who is the audience?", detail["messages"][-1]["content"])
                self.assertEqual(answer.status_code, 202)
                followup = AgentExecution.objects.get(id=answer.data["execution_id"])
                self.assertEqual(followup.context_parent_id, execution.id)
                self.assertEqual(
                    followup.configuration["question_execution_id"], execution.id
                )
                self.assertIsNone(self.client.get(url).data["pending_question"])
                provider = self._run(
                    followup, [text_turn("I will write for first-year students.")]
                )
                self.assertEqual(
                    provider.calls[0][-1].content[0].text, "First-year students"
                )
                self.assertTrue(
                    any(
                        isinstance(block, ToolResultBlock)
                        and block.content == self.question
                        for message in provider.calls[0]
                        for block in message.content
                    )
                )

    def test_repeated_and_foreign_question_answers_are_rejected_without_new_turns(self):
        for base_url in self.chat_urls:
            with self.subTest(base_url=base_url):
                # Arrange
                url = self._create_chat(base_url)
                execution = self._ask(url)
                other_url = self._create_chat(base_url)
                before = AgentExecution.objects.count()

                # Act
                foreign = self._post(
                    other_url, "Public", question_execution_id=execution.id
                )
                accepted = self._post(url, "Public", question_execution_id=execution.id)
                duplicate_running = self._post(
                    url, "Public", question_execution_id=execution.id
                )
                followup = AgentExecution.objects.get(id=accepted.data["execution_id"])
                self._run(followup, [text_turn("Done.")])
                duplicate_finished = self._post(
                    url, "Public", question_execution_id=execution.id
                )

                # Assert
                self.assertEqual(foreign.status_code, 400)
                self.assertEqual(accepted.status_code, 202)
                self.assertEqual(duplicate_running.status_code, 409)
                self.assertEqual(duplicate_finished.status_code, 400)
                self.assertEqual(AgentExecution.objects.count(), before + 1)

    def test_ordinary_message_can_change_direction_without_question_id(self):
        for base_url in self.chat_urls:
            with self.subTest(base_url=base_url):
                # Arrange
                url = self._create_chat(base_url)
                self._ask(url)

                # Act
                response = self._post(url, "Never mind; just summarize it.")

                # Assert
                self.assertEqual(response.status_code, 202)
                self.assertIsNone(self.client.get(url).data["pending_question"])
                followup = AgentExecution.objects.get(id=response.data["execution_id"])
                self._run(followup, [text_turn("Here is the summary.")])

    def test_question_publication_is_repaired_after_failure(self):
        # Arrange
        url = self._create_chat(self.chat_urls[0])
        with patch.object(
            DatabaseAgentRecorder,
            "publish_assistant_output",
            side_effect=RuntimeError("unavailable"),
        ):
            execution = self._ask(url)
        self.assertFalse(
            execution.conversation.chat_messages.filter(
                generated_by_execution=execution
            ).exists()
        )

        # Act
        detail = self.client.get(url).data

        # Assert
        self.assertEqual(
            detail["pending_question"]["question"], self.question["question"]
        )
        self.assertEqual(detail["messages"][-1]["role"], "assistant")
        self.assertIn(self.question["question"], detail["messages"][-1]["content"])
        self.assertFalse(detail["executions"][-1]["assistant_message_pending"])

    def test_another_user_cannot_read_or_answer_the_question(self):
        # Arrange
        other = get_user_model().objects.create_user(
            username="other-question-user",
            email="other-question@researchhub_test.com",
            password="password",
            is_staff=True,
        )
        for base_url in self.chat_urls:
            with self.subTest(base_url=base_url):
                self.client.force_authenticate(self.user)
                url = self._create_chat(base_url)
                execution = self._ask(url)
                self.client.force_authenticate(other)

                # Act
                detail = self.client.get(url)
                answer = self._post(url, "Public", question_execution_id=execution.id)

                # Assert
                self.assertEqual(detail.status_code, 404)
                self.assertEqual(answer.status_code, 404)
                self.assertEqual(execution.conversation.executions.count(), 1)
