from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from note.tests.helpers import create_note
from research_ai.models import AgentConversation, AgentMessageScreening
from research_ai.services.agent_persistence import AgentConversationService
from research_ai.services.message_screening import MessageScreeningService
from research_ai.services.message_screening.jev_client import (
    MODEL,
    Decision,
    DecisionError,
)
from research_ai.services.message_screening.service import (
    MAX_MESSAGE_CHARS,
    QUESTIONS,
)
from research_ai.tests.agent_files.helpers import make_file


def jev_client(**answers) -> Mock:
    client = Mock(model=MODEL)
    client.decide.return_value = Decision(
        model="typesafe/jev-1.13-20260917", answers=answers, cost_microusd=23
    )
    return client


class MessageScreeningServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="screened@researchhub_test.com",
            email="screened@researchhub_test.com",
        )
        self.conversation = AgentConversation.objects.create(
            user=self.user, workflow="notebook_chat"
        )
        self.message = AgentConversationService().add_human_message(
            self.conversation, "Write an SEO article about keto gummies."
        )

    def test_records_the_probabilities_and_flags_a_high_one(self):
        cases = (
            ({"promotional": 0.99, "off_purpose": 0.4}, True),
            ({"promotional": 0.1, "off_purpose": 0.8}, True),
            ({"promotional": 0.79, "off_purpose": 0.2}, False),
        )
        for answers, flagged in cases:
            with self.subTest(answers=answers):
                # Arrange
                AgentMessageScreening.objects.all().delete()
                service = MessageScreeningService(client=jev_client(**answers))

                # Act
                screening = service.screen(self.message)

                # Assert
                self.assertEqual(screening.message, self.message)
                self.assertEqual(screening.model, "typesafe/jev-1.13-20260917")
                self.assertEqual(screening.promotional, answers["promotional"])
                self.assertEqual(screening.off_purpose, answers["off_purpose"])
                self.assertEqual(screening.flagged, flagged)
                self.assertEqual(screening.cost_microusd, 23)
                self.assertEqual(screening.error, "")

    def test_sends_the_message_with_its_note_and_files(self):
        # Arrange
        note, content = create_note(
            self.user,
            organization=None,
            title="Keto gummies guide",
            body="Buy now at example.com",
        )
        note.latest_version = content
        note.save(update_fields=["latest_version"])
        make_file(self.user, message=self.message, filename="a.pdf", text="Ad copy")
        make_file(self.user, message=self.message, filename="b.png", text="")
        client = jev_client(promotional=0.9, off_purpose=0.9)

        # Act
        MessageScreeningService(client=client).screen(self.message, note=note)

        # Assert
        state, questions = client.decide.call_args.args
        self.assertEqual(
            state,
            {
                "workflow": "notebook_chat",
                "message": "Write an SEO article about keto gummies.",
                "note": {
                    "title": "Keto gummies guide",
                    "type": note.document_type,
                    "text": "Buy now at example.com",
                },
                "attached_files": [
                    {"name": "a.pdf", "text": "Ad copy"},
                    {"name": "b.png", "text": ""},
                ],
            },
        )
        self.assertEqual(questions, QUESTIONS)

    def test_sends_the_users_earlier_messages_oldest_first(self):
        # Arrange
        conversations = AgentConversationService()
        for text in ("one", "two", "three", "four"):
            conversations.add_human_message(self.conversation, text)
        latest = conversations.add_human_message(
            self.conversation, "i mean for social media content"
        )
        client = jev_client(promotional=0.9, off_purpose=0.9)

        # Act
        MessageScreeningService(client=client).screen(latest)

        # Assert
        state, _questions = client.decide.call_args.args
        self.assertEqual(state["earlier_messages"], ["two", "three", "four"])
        self.assertEqual(state["message"], "i mean for social media content")

    def test_a_long_message_is_cut_before_it_is_sent(self):
        # Arrange
        self.message.content = "a" * (MAX_MESSAGE_CHARS + 100)
        client = jev_client(promotional=0.1, off_purpose=0.1)

        # Act
        MessageScreeningService(client=client).screen(self.message)

        # Assert
        (state, _questions) = client.decide.call_args.args
        self.assertEqual(len(state["message"]), MAX_MESSAGE_CHARS)

    def test_a_failed_decision_is_recorded_without_scores(self):
        # Arrange
        client = Mock(model=MODEL)
        client.decide.side_effect = DecisionError("Jev returned no decision: 503")

        # Act
        screening = MessageScreeningService(client=client).screen(self.message)

        # Assert
        self.assertEqual(screening.model, MODEL)
        self.assertIsNone(screening.promotional)
        self.assertIsNone(screening.off_purpose)
        self.assertFalse(screening.flagged)
        self.assertIn("503", screening.error)

    def test_a_retried_turn_reuses_the_messages_screening(self):
        # Arrange
        client = jev_client(promotional=0.9, off_purpose=0.9)
        service = MessageScreeningService(client=client)
        first = service.screen(self.message)

        # Act
        second = service.screen(self.message)

        # Assert
        self.assertEqual(second, first)
        client.decide.assert_called_once()

    @override_settings(RESEARCH_AI_MESSAGE_SCREENING=False, OPENROUTER_API_KEY="k")
    def test_nothing_is_screened_when_screening_is_off(self):
        # Act
        screening = MessageScreeningService().screen(self.message)

        # Assert
        self.assertIsNone(screening)
        self.assertFalse(AgentMessageScreening.objects.exists())
