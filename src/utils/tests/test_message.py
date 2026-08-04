from django.core import mail
from django.test import TestCase, override_settings

from utils.message import UnsubscribeUrls, _is_allowed_recipient, deliver_email

TEMPLATE_TXT = "general_email_message.txt"
TEMPLATE_HTML = "general_email_message.html"
BASE_CONTEXT = {"action": {"message": "hello"}, "subject": "Test"}


class IsAllowedRecipientTests(TestCase):
    def test_allows_any_valid_email_in_test_mode(self):
        self.assertTrue(_is_allowed_recipient("anyone@example.com"))

    @override_settings(TESTING=False, EMAIL_WHITELIST=["a@example.com"])
    def test_allows_whitelisted_email(self):
        self.assertTrue(_is_allowed_recipient("a@example.com"))

    @override_settings(TESTING=False, EMAIL_WHITELIST=["other@example.com"])
    def test_rejects_non_whitelisted_email(self):
        self.assertFalse(_is_allowed_recipient("blocked@example.com"))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PRODUCTION=False,
)
class DeliverEmailTests(TestCase):
    def _send(self, recipients="user@example.com", **overrides):
        kwargs = {
            "recipients": recipients,
            "template": TEMPLATE_TXT,
            "subject": "Test",
            "email_context": {**BASE_CONTEXT},
            "html_template": TEMPLATE_HTML,
        }
        kwargs.update(overrides)
        return deliver_email(**kwargs)

    def test_sends_to_valid_recipient(self):
        # Act
        result = self._send()

        # Assert
        self.assertEqual(result["success"], ["user@example.com"])
        self.assertEqual(len(mail.outbox), 1)

    def test_sets_precedence_bulk(self):
        # Act
        self._send()

        # Assert
        msg = mail.outbox[0]
        self.assertEqual(msg.extra_headers["Precedence"], "bulk")

    def test_list_unsubscribe_headers(self):
        # Act
        self._send(
            unsubscribe_urls={
                "user@example.com": UnsubscribeUrls(
                    human="https://example.com/email/preferences",
                    one_click="https://example.com/unsubscribe",
                )
            },
        )

        # Assert
        headers = mail.outbox[0].extra_headers
        self.assertEqual(
            headers["List-Unsubscribe"],
            "<https://example.com/unsubscribe>",
        )
        self.assertEqual(
            headers["List-Unsubscribe-Post"],
            "List-Unsubscribe=One-Click",
        )

    def test_does_not_mutate_email_context(self):
        # Arrange
        context = {**BASE_CONTEXT}

        # Act
        self._send(
            recipients=["a@example.com", "b@example.com"],
            email_context=context,
            unsubscribe_urls={
                "a@example.com": UnsubscribeUrls(
                    human="https://example.com/preferences/a",
                    one_click="https://example.com/unsubscribe/a",
                ),
                "b@example.com": UnsubscribeUrls(
                    human="https://example.com/preferences/b",
                    one_click="https://example.com/unsubscribe/b",
                ),
            },
        )

        # Assert
        self.assertEqual(context, BASE_CONTEXT)

    def test_reply_to_is_set(self):
        # Act
        self._send(reply_to="reply@example.com")

        # Assert
        self.assertEqual(mail.outbox[0].reply_to, ["reply@example.com"])
