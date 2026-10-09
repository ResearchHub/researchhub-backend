"""Unit tests for expert-finder SES email validation"""

from unittest.mock import MagicMock

from botocore.exceptions import ClientError
from django.test import SimpleTestCase

from mailing_list.services.email_insights_service import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
)
from research_ai.services.expert_finder.email_validation import (
    EMAIL_VALIDATE,
    EmailValidateToolset,
    EmailValidationService,
    is_role_local_part,
)


def _insights(
    *,
    is_valid=CONFIDENCE_HIGH,
    mailbox_exists=CONFIDENCE_HIGH,
    is_disposable=CONFIDENCE_LOW,
    is_role_address=CONFIDENCE_LOW,
    is_random_input=CONFIDENCE_LOW,
    has_valid_syntax=CONFIDENCE_HIGH,
    has_valid_dns=CONFIDENCE_HIGH,
):
    return {
        "MailboxValidation": {
            "IsValid": {"ConfidenceVerdict": is_valid},
            "Evaluations": {
                "HasValidSyntax": {"ConfidenceVerdict": has_valid_syntax},
                "HasValidDnsRecords": {"ConfidenceVerdict": has_valid_dns},
                "MailboxExists": {"ConfidenceVerdict": mailbox_exists},
                "IsDisposable": {"ConfidenceVerdict": is_disposable},
                "IsRoleAddress": {"ConfidenceVerdict": is_role_address},
                "IsRandomInput": {"ConfidenceVerdict": is_random_input},
            },
        }
    }


class RoleLocalPartTests(SimpleTestCase):
    def test_rejects_known_role_locals(self):
        # Arrange / Act / Assert
        for address in (
            "info@university.edu",
            "Contact@dept.edu",
            "admin+lab@uni.edu",
            "no-reply@example.com",
            "no.reply@example.com",
        ):
            with self.subTest(address=address):
                self.assertTrue(is_role_local_part(address))

    def test_allows_personal_locals(self):
        # Arrange / Act / Assert
        for address in (
            "jane.doe@university.edu",
            "jdoe@mit.edu",
            "ada.lovelace@ox.ac.uk",
        ):
            with self.subTest(address=address):
                self.assertFalse(is_role_local_part(address))


class EmailValidationServiceTests(SimpleTestCase):
    def setUp(self):
        self.client = MagicMock()
        self.service = EmailValidationService(client=self.client)

    def test_accepts_medium_or_better_overall_and_mailbox(self):
        # Arrange
        self.client.get_email_address_insights.return_value = _insights(
            is_valid=CONFIDENCE_MEDIUM,
            mailbox_exists=CONFIDENCE_MEDIUM,
        )
        # Act
        result = self.service.validate("Jane.Doe@University.EDU")
        # Assert
        self.assertTrue(result.accepted)
        self.assertEqual(result.email, "jane.doe@university.edu")
        self.assertIsNone(result.reason)
        self.client.get_email_address_insights.assert_called_once_with(
            EmailAddress="jane.doe@university.edu"
        )

    def test_rejects_low_is_valid(self):
        # Arrange
        self.client.get_email_address_insights.return_value = _insights(
            is_valid=CONFIDENCE_LOW,
            mailbox_exists=CONFIDENCE_HIGH,
        )
        # Act
        result = self.service.validate("jane@university.edu")
        # Assert
        self.assertFalse(result.accepted)
        self.assertIn("IsValid", result.reason or "")

    def test_rejects_low_mailbox_exists(self):
        # Arrange
        self.client.get_email_address_insights.return_value = _insights(
            is_valid=CONFIDENCE_HIGH,
            mailbox_exists=CONFIDENCE_LOW,
        )
        # Act
        result = self.service.validate("jane@university.edu")
        # Assert
        self.assertFalse(result.accepted)
        self.assertIn("MailboxExists", result.reason or "")

    def test_rejects_role_local_without_calling_ses(self):
        # Arrange / Act
        result = self.service.validate("info@university.edu")
        # Assert
        self.assertFalse(result.accepted)
        self.assertIn("role-like", result.reason or "")
        self.client.get_email_address_insights.assert_not_called()

    def test_rejects_disposable_and_ses_role_flags(self):
        # Arrange / Act / Assert
        cases = (
            ("disposable", {"is_disposable": CONFIDENCE_MEDIUM}),
            ("role address", {"is_role_address": CONFIDENCE_HIGH}),
            ("random-looking", {"is_random_input": CONFIDENCE_MEDIUM}),
        )
        for needle, kwargs in cases:
            with self.subTest(needle=needle):
                self.client.get_email_address_insights.return_value = _insights(
                    **kwargs
                )
                result = self.service.validate("person@university.edu")
                self.assertFalse(result.accepted)
                self.assertIn(needle, result.reason or "")

    def test_ses_error_fails_closed(self):
        # Arrange
        self.client.get_email_address_insights.side_effect = ClientError(
            {"Error": {"Code": "Throttling", "Message": "slow"}},
            "GetEmailAddressInsights",
        )
        # Act
        result = self.service.validate("jane@university.edu")
        # Assert
        self.assertFalse(result.accepted)
        self.assertIn("ses insights unavailable", result.reason or "")

    def test_invalid_syntax_rejected(self):
        # Arrange / Act
        result = self.service.validate("not-an-email")
        # Assert
        self.assertFalse(result.accepted)
        self.assertIn("syntax", result.reason or "")
        self.client.get_email_address_insights.assert_not_called()


class GateSubmittedExpertsTests(SimpleTestCase):
    def setUp(self):
        self.client = MagicMock()
        self.service = EmailValidationService(client=self.client)

    def test_keeps_only_accepted_emails_and_normalizes(self):
        # Arrange
        self.client.get_email_address_insights.return_value = _insights()
        experts = [
            {"email": "Jane@Uni.EDU", "openalex_author_id": "A1"},
            {"email": "info@uni.edu", "openalex_author_id": "A2"},
            {"email": "jane@uni.edu", "openalex_author_id": "A3"},  # duplicate
            {"email": "", "openalex_author_id": "A4"},
            "not-a-dict",
        ]
        # Act
        kept, drops = self.service.gate_submitted_experts(experts)
        # Assert
        self.assertEqual(kept, [{"email": "jane@uni.edu", "openalex_author_id": "A1"}])
        self.assertEqual(len(drops), 4)
        self.assertTrue(any("role-like" in d for d in drops))
        self.assertTrue(any("duplicate" in d for d in drops))

    def test_empty_list_returns_empty(self):
        # Arrange / Act
        kept, drops = self.service.gate_submitted_experts([])
        # Assert
        self.assertEqual(kept, [])
        self.assertEqual(drops, [])


class EmailValidateToolsetTests(SimpleTestCase):
    def test_tool_returns_verdict_dict(self):
        # Arrange
        client = MagicMock()
        client.get_email_address_insights.return_value = _insights()
        toolset = EmailValidateToolset(
            service=EmailValidationService(client=client)
        ).as_toolset()
        # Act
        result, stop = toolset.dispatch(EMAIL_VALIDATE, {"email": "ada@uni.edu"})
        # Assert
        self.assertFalse(stop)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["email"], "ada@uni.edu")
        self.assertEqual(result["is_valid"], CONFIDENCE_HIGH)

    def test_tool_requires_email(self):
        # Arrange
        toolset = EmailValidateToolset(
            service=EmailValidationService(client=MagicMock())
        ).as_toolset()
        # Act
        result, stop = toolset.dispatch(EMAIL_VALIDATE, {})
        # Assert
        self.assertFalse(stop)
        self.assertIn("error", result)
