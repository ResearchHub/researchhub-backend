from unittest.mock import MagicMock

from django.test import TestCase

from research_ai.models import EmailTemplate
from research_ai.services.outreach.template_rewrite_service import (
    PlaceholderMismatchError,
    TemplateNotFoundError,
    TemplateRewriteService,
    parse_rewrite_response,
)
from user.tests.helpers import create_random_authenticated_user


class ParseRewriteResponseTests(TestCase):
    def test_parses_json_object(self):
        # Arrange
        raw = '{"email_subject": "Hi {{expert.name}}", "email_body": "Body"}'

        # Act
        subject, body = parse_rewrite_response(raw)

        # Assert
        self.assertEqual(subject, "Hi {{expert.name}}")
        self.assertEqual(body, "Body")

    def test_parses_fenced_json(self):
        # Arrange
        raw = '```json\n{"email_subject": "S", "email_body": "B"}\n```'

        # Act
        subject, body = parse_rewrite_response(raw)

        # Assert
        self.assertEqual(subject, "S")
        self.assertEqual(body, "B")


class TemplateRewriteServiceTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("trw")
        self.llm = MagicMock()
        self.service = TemplateRewriteService(llm=self.llm)
        self.source = EmailTemplate.objects.create(
            created_by=self.user,
            name="Invite",
            email_subject="Hello {{expert.name}}",
            email_body="Join {{rfp.title}} at {{expert.affiliation}}",
        )

    def test_rewrite_saves_new_template_when_placeholders_match(self):
        # Arrange
        self.llm.invoke.return_value = (
            '{"email_subject": "Hi {{expert.name}}",'
            ' "email_body": "Please join {{rfp.title}} with {{expert.affiliation}}"}'
        )

        # Act
        rewritten = self.service.rewrite_template(self.user, self.source.id)

        # Assert
        self.assertNotEqual(rewritten.id, self.source.id)
        self.assertEqual(rewritten.created_by_id, self.user.id)
        self.assertEqual(rewritten.name, "Invite (rewritten)")
        self.assertEqual(rewritten.email_subject, "Hi {{expert.name}}")
        self.assertIn("{{rfp.title}}", rewritten.email_body)
        self.assertIn("{{expert.affiliation}}", rewritten.email_body)
        self.llm.invoke.assert_called_once()

    def test_rewrite_rejects_changed_placeholder_set(self):
        # Arrange: drops expert.affiliation, adds user.full_name
        self.llm.invoke.return_value = (
            '{"email_subject": "Hi {{expert.name}}",'
            ' "email_body": "Join {{rfp.title}} — {{user.full_name}}"}'
        )

        # Act / Assert
        with self.assertRaises(PlaceholderMismatchError):
            self.service.rewrite_template(self.user, self.source.id)
        self.assertEqual(EmailTemplate.objects.count(), 1)

    def test_rewrite_rejects_missing_template(self):
        # Arrange / Act / Assert
        with self.assertRaises(TemplateNotFoundError):
            self.service.rewrite_template(self.user, 999999)
