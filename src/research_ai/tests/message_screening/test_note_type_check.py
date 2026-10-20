from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from note.tests.helpers import create_note
from research_ai.models import AgentConversation, AgentExecution, AgentNoteTypeCheck
from research_ai.services.agent_persistence import AgentConversationService
from research_ai.services.message_screening import (
    NoteTypeCheckService,
    switch_notice,
)
from research_ai.services.message_screening.jev_client import (
    MODEL,
    Decision,
    DecisionError,
)
from research_ai.services.message_screening.note_type_check import QUESTIONS
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
    PREREGISTRATION,
)


def jev_client(**answers) -> Mock:
    client = Mock(model=MODEL)
    client.decide.return_value = Decision(
        model="typesafe/jev-1.13-20260917", answers=answers, cost_microusd=21
    )
    return client


class NoteTypeCheckServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="typed@researchhub_test.com",
            email="typed@researchhub_test.com",
        )
        self.note, _ = create_note(self.user, organization=None, title="BP pilot")
        self._set_type(GRANT)
        self.conversation = AgentConversation.objects.create(
            user=self.user, workflow="notebook_chat"
        )
        self.messages = AgentConversationService()
        self.message = self.messages.add_human_message(
            self.conversation, "Help me get my 20-patient pilot funded."
        )

    def _set_type(self, document_type):
        self.note.document_type = document_type
        self.note.save(update_fields=["document_type"])

    def _turn(self, message, status):
        AgentExecution.objects.create(
            conversation=self.conversation,
            attempt=message.sequence,
            trigger_message=message,
            status=status,
        )

    def test_suggests_the_other_type_when_jev_is_confident(self):
        cases = (
            (GRANT, "proposal_in_rfp", 0.95, True, PREREGISTRATION),
            (GRANT, "proposal_in_rfp", 0.79, False, PREREGISTRATION),
            (PREREGISTRATION, "rfp_in_proposal", 0.9, True, GRANT),
        )
        for note_type, question, probability, suggested, suggested_type in cases:
            with self.subTest(note_type=note_type, probability=probability):
                # Arrange
                AgentNoteTypeCheck.objects.all().delete()
                self._set_type(note_type)
                client = jev_client(**{question: probability})

                # Act
                check = NoteTypeCheckService(client=client).check(
                    self.message, self.note
                )

                # Assert
                _state, questions = client.decide.call_args.args
                self.assertEqual(questions, dict([QUESTIONS[note_type]]))
                self.assertEqual(check.note_type, note_type)
                self.assertEqual(check.suggested_type, suggested_type)
                self.assertEqual(check.probability, probability)
                self.assertEqual(check.suggested, suggested)
                self.assertEqual(check.model, "typesafe/jev-1.13-20260917")
                self.assertEqual(check.cost_microusd, 21)

    def test_sends_the_message_with_its_note(self):
        # Arrange
        client = jev_client(proposal_in_rfp=0.9)

        # Act
        NoteTypeCheckService(client=client).check(self.message, self.note)

        # Assert
        state, _questions = client.decide.call_args.args
        self.assertEqual(state["message"], "Help me get my 20-patient pilot funded.")
        self.assertEqual(state["note"]["title"], "BP pilot")
        self.assertEqual(state["note"]["type"], GRANT)

    def test_checks_only_rfp_and_proposal_notes(self):
        # Arrange
        self._set_type(DISCUSSION)
        client = jev_client(proposal_in_rfp=0.9)
        service = NoteTypeCheckService(client=client)

        # Act
        checks = [
            service.check(self.message, self.note),
            service.check(self.message, None),
        ]

        # Assert
        self.assertEqual(checks, [None, None])
        client.decide.assert_not_called()

    def test_does_not_ask_again_once_a_turn_offered_a_switch(self):
        # Arrange
        client = jev_client(proposal_in_rfp=0.9)
        service = NoteTypeCheckService(client=client)
        service.check(self.message, self.note)
        self._turn(self.message, AgentExecution.Status.SUCCEEDED)
        later = self.messages.add_human_message(self.conversation, "No, keep it.")

        # Act
        check = service.check(later, self.note)

        # Assert
        self.assertIsNone(check)
        client.decide.assert_called_once()

    def test_asks_again_when_the_turn_that_offered_it_failed(self):
        # Arrange
        client = jev_client(proposal_in_rfp=0.9)
        service = NoteTypeCheckService(client=client)
        service.check(self.message, self.note)
        self._turn(self.message, AgentExecution.Status.FAILED)
        later = self.messages.add_human_message(self.conversation, "Hello?")

        # Act
        check = service.check(later, self.note)

        # Assert
        self.assertTrue(check.suggested)

    def test_a_retried_turn_reuses_the_messages_check(self):
        # Arrange
        client = jev_client(proposal_in_rfp=0.9)
        service = NoteTypeCheckService(client=client)
        first = service.check(self.message, self.note)
        self._turn(self.message, AgentExecution.Status.SUCCEEDED)

        # Act
        second = service.check(self.message, self.note)

        # Assert
        self.assertEqual(second, first)
        client.decide.assert_called_once()

    def test_a_failed_decision_is_recorded_without_a_suggestion(self):
        # Arrange
        client = Mock(model=MODEL)
        client.decide.side_effect = DecisionError("Jev returned no decision: 503")

        # Act
        check = NoteTypeCheckService(client=client).check(self.message, self.note)

        # Assert
        self.assertIsNone(check.probability)
        self.assertFalse(check.suggested)
        self.assertIn("503", check.error)

    @override_settings(RESEARCH_AI_NOTE_TYPE_CHECK=False, OPENROUTER_API_KEY="k")
    def test_nothing_is_checked_when_checking_is_off(self):
        # Act
        check = NoteTypeCheckService().check(self.message, self.note)

        # Assert
        self.assertIsNone(check)
        self.assertFalse(AgentNoteTypeCheck.objects.exists())


class SwitchNoticeTests(SimpleTestCase):
    def setUp(self):
        self.note = Mock(document_type=GRANT)

    def test_tells_the_agent_to_offer_the_switch(self):
        cases = ((GRANT, "switched to a proposal"), (PREREGISTRATION, "to an RFP"))
        for note_type, offer in cases:
            with self.subTest(note_type=note_type):
                # Arrange
                check = AgentNoteTypeCheck(note_type=note_type, suggested=True)
                self.note.document_type = note_type

                # Act
                notice = switch_notice(check, self.note)

                # Assert
                self.assertTrue(notice.startswith("[Notice from the system"))
                self.assertIn(offer, notice)
                self.assertIn("do not raise it again", notice)

    def test_no_notice_without_a_suggestion_for_the_notes_current_type(self):
        cases = (
            None,
            AgentNoteTypeCheck(note_type=GRANT, suggested=False),
            # The user switched the note themself before a retry.
            AgentNoteTypeCheck(note_type=PREREGISTRATION, suggested=True),
        )
        for check in cases:
            with self.subTest(check=check):
                # Act
                notice = switch_notice(check, self.note)

                # Assert
                self.assertIsNone(notice)
