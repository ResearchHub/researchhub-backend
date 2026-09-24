"""Unit tests for the SES email insights client."""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from mailing_list.services.email_insights_service import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    EmailInsightsService,
    confidence_at_least,
    confidence_verdict,
    parse_mailbox_validation,
)


class ConfidenceHelperTests(SimpleTestCase):
    def test_confidence_at_least(self):
        # Arrange / Act / Assert
        self.assertTrue(confidence_at_least(CONFIDENCE_HIGH, CONFIDENCE_MEDIUM))
        self.assertTrue(confidence_at_least(CONFIDENCE_MEDIUM, CONFIDENCE_MEDIUM))
        self.assertFalse(confidence_at_least(CONFIDENCE_LOW, CONFIDENCE_MEDIUM))
        self.assertFalse(confidence_at_least(None, CONFIDENCE_MEDIUM))
        self.assertFalse(confidence_at_least("nope", CONFIDENCE_MEDIUM))

    def test_confidence_verdict_normalizes(self):
        # Arrange / Act / Assert
        self.assertEqual(
            confidence_verdict({"ConfidenceVerdict": " high "}), CONFIDENCE_HIGH
        )
        self.assertIsNone(confidence_verdict({}))
        self.assertIsNone(confidence_verdict(None))


class ParseMailboxValidationTests(SimpleTestCase):
    def test_parses_nested_evaluations(self):
        # Arrange
        response = {
            "MailboxValidation": {
                "IsValid": {"ConfidenceVerdict": CONFIDENCE_HIGH},
                "Evaluations": {
                    "MailboxExists": {"ConfidenceVerdict": CONFIDENCE_MEDIUM},
                    "IsDisposable": {"ConfidenceVerdict": CONFIDENCE_LOW},
                    "IsRoleAddress": {"ConfidenceVerdict": CONFIDENCE_LOW},
                    "IsRandomInput": {"ConfidenceVerdict": CONFIDENCE_LOW},
                    "HasValidSyntax": {"ConfidenceVerdict": CONFIDENCE_HIGH},
                    "HasValidDnsRecords": {"ConfidenceVerdict": CONFIDENCE_MEDIUM},
                },
            }
        }
        # Act
        insights = parse_mailbox_validation(response)
        # Assert
        self.assertEqual(insights.is_valid, CONFIDENCE_HIGH)
        self.assertEqual(insights.mailbox_exists, CONFIDENCE_MEDIUM)
        self.assertEqual(insights.is_disposable, CONFIDENCE_LOW)
        self.assertEqual(insights.has_valid_syntax, CONFIDENCE_HIGH)
        self.assertEqual(insights.has_valid_dns_records, CONFIDENCE_MEDIUM)


class EmailInsightsServiceTests(SimpleTestCase):
    def test_get_insights_calls_ses_and_parses(self):
        # Arrange
        client = MagicMock()
        client.get_email_address_insights.return_value = {
            "MailboxValidation": {
                "IsValid": {"ConfidenceVerdict": CONFIDENCE_HIGH},
                "Evaluations": {
                    "MailboxExists": {"ConfidenceVerdict": CONFIDENCE_MEDIUM},
                },
            }
        }
        service = EmailInsightsService(client=client)

        # Act
        insights = service.get_insights("jane@uni.edu")

        # Assert
        client.get_email_address_insights.assert_called_once_with(
            EmailAddress="jane@uni.edu"
        )
        self.assertEqual(insights.is_valid, CONFIDENCE_HIGH)
        self.assertEqual(insights.mailbox_exists, CONFIDENCE_MEDIUM)

    def test_get_raw_insights_returns_response(self):
        # Arrange
        client = MagicMock()
        client.get_email_address_insights.return_value = {"ok": True}
        service = EmailInsightsService(client=client)

        # Act
        raw = service.get_raw_insights("a@b.edu")

        # Assert
        self.assertEqual(raw, {"ok": True})
