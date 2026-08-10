from urllib.parse import unquote

from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings

from mailing_list.lib import send_email, send_transactional_email
from mailing_list.models import EmailOptOut
from mailing_list.services import EmailSubscriptionService

TEMPLATE_HTML = "general_email_message.html"
BASE_CONTEXT = {"action": {"message": "hello"}, "subject": "Test"}


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PRODUCTION=False,
)
class SendEmailTests(TestCase):
    """`send_email` suppresses opt-outs and attaches unsubscribe links."""

    def _send(self, recipients, **overrides):
        kwargs = {
            "recipients": recipients,
            "subject": "Test",
            "email_context": {**BASE_CONTEXT},
            "html_template": TEMPLATE_HTML,
        }
        kwargs.update(overrides)
        return send_email(**kwargs)

    def test_sends_to_recipient_without_a_suppression_record(self):
        # Act
        self._send(["good@example.com"])

        # Assert
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["good@example.com"])

    def test_accepts_a_single_recipient_string(self):
        # Act
        self._send("good@example.com")

        # Assert
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["good@example.com"])

    def test_excludes_opted_out_recipient(self):
        # Arrange
        EmailOptOut.add("optout@example.com")

        # Act
        self._send(["optout@example.com"])

        # Assert
        self.assertEqual(len(mail.outbox), 0)

    def test_excludes_opted_out_recipient_regardless_of_casing(self):
        # Arrange
        EmailOptOut.add("optout@example.com")

        # Act
        self._send(["OptOut@Example.com"])

        # Assert
        self.assertEqual(len(mail.outbox), 0)

    def test_sends_only_to_unsuppressed_recipients_in_a_mixed_list(self):
        # Arrange
        EmailOptOut.add("optout@example.com")

        # Act
        self._send(["optout@example.com", "good@example.com"])

        # Assert
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["good@example.com"])

    def test_sets_one_click_unsubscribe_headers(self):
        # Act
        self._send(["good@example.com"])

        # Assert
        headers = mail.outbox[0].extra_headers
        self.assertEqual(headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        self.assertIn(
            f"{settings.BASE_FRONTEND_URL}/api/email/unsubscribe?",
            headers["List-Unsubscribe"],
        )

    def test_list_unsubscribe_url_carries_a_code_the_service_accepts(self):
        # Arrange
        service = EmailSubscriptionService()

        # Act
        self._send(["good@example.com"])

        # Assert: the header URL round-trips back to the same address. The code
        # is percent-encoded in the query string, as Django decodes it for the
        # view; do the same here.
        header = mail.outbox[0].extra_headers["List-Unsubscribe"]
        code = unquote(header.split("code=")[1].rstrip(">"))
        service.unsubscribe(code)
        self.assertEqual(
            EmailOptOut.filter_opted_out(["good@example.com"]), {"good@example.com"}
        )

    def test_each_recipient_gets_its_own_unsubscribe_url(self):
        # Act
        self._send(["a@example.com", "b@example.com"])

        # Assert
        first, second = (msg.extra_headers["List-Unsubscribe"] for msg in mail.outbox)
        self.assertNotEqual(first, second)

    def test_rejects_a_send_with_neither_template(self):
        # Act & Assert: a body-less message is a programming error, not a send
        with self.assertRaises(ValueError):
            self._send(["good@example.com"], html_template=None)

        self.assertEqual(len(mail.outbox), 0)

    def test_derives_the_text_body_from_the_html_when_no_text_template(self):
        # Act
        self._send(["good@example.com"])

        # Assert
        self.assertIn("hello", mail.outbox[0].body)

    def test_derived_text_body_excludes_embedded_css(self):
        # Arrange: this template carries a <style> block and has no text template
        context = {"user_name": "user1", "subject": "subject1"}

        # Act
        self._send(
            ["good@example.com"],
            html_template="organization_invite.html",
            email_context=context,
        )

        # Assert: the CSS rules must not leak into the text part
        body = mail.outbox[0].body
        self.assertIn("invited you", body)
        self.assertNotIn("@media", body)
        self.assertNotIn("{", body)

    def test_derived_text_body_keeps_link_urls(self):
        # Act
        self._send(["good@example.com"])

        # Assert: a text-only reader must still be able to follow the links
        body = mail.outbox[0].body
        self.assertIn(
            f"Unsubscribe ({settings.BASE_FRONTEND_URL}/email/unsubscribe/?code=",
            body,
        )

    def test_derived_text_body_decodes_html_entities(self):
        # Arrange: autoescaping encodes the apostrophe as &#x27; in the HTML
        context = {"action": {"message": "it's here"}, "subject": "subject1"}

        # Act
        self._send(["good@example.com"], email_context=context)

        # Assert
        body = mail.outbox[0].body
        self.assertIn("it's here", body)
        self.assertNotIn("&#x27;", body)

    def test_derived_text_body_has_no_ragged_html_whitespace(self):
        # Act
        self._send(["good@example.com"])

        # Assert
        # no indentation carried over from the HTML markup and no runs of blank lines
        body = mail.outbox[0].body
        self.assertFalse(
            any(line != line.strip() for line in body.splitlines()),
            "text body has lines with leading/trailing whitespace",
        )
        self.assertNotIn("\n\n\n", body)
        self.assertEqual(body, body.strip())

    def test_renders_assets_base_url_without_the_caller_supplying_it(self):
        # Act
        self._send(["good@example.com"])

        # Assert
        html_body = mail.outbox[0].alternatives[0][0]
        self.assertIn(f"{settings.ASSETS_BASE_URL}/email_assets/", html_body)

    def test_marks_mail_as_bulk(self):
        # Act
        self._send(["good@example.com"])

        # Assert
        self.assertEqual(mail.outbox[0].extra_headers["Precedence"], "bulk")

    def test_sets_reply_to(self):
        # Act
        self._send(["good@example.com"], reply_to="reply@example.com")

        # Assert
        self.assertEqual(mail.outbox[0].reply_to, ["reply@example.com"])

    @override_settings(TESTING=False, EMAIL_WHITELIST=["allowed@example.com"])
    def test_outside_production_sends_only_to_whitelisted_addresses(self):
        # Act
        self._send(["allowed@example.com", "blocked@example.com"])

        # Assert
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["allowed@example.com"])

    @override_settings(TESTING=False, EMAIL_WHITELIST=["@example.com"])
    def test_whitelist_entry_can_be_a_whole_domain(self):
        # Act
        self._send(["Anyone@Example.com", "blocked@other.com"])

        # Assert
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["Anyone@Example.com"])

    def test_html_footer_link_unsubscribes_the_recipient(self):
        # Arrange
        service = EmailSubscriptionService()

        # Act
        self._send(["good@example.com"])

        # Assert: the footer link round-trips back to the same address
        html_body = mail.outbox[0].alternatives[0][0]
        self.assertIn("code=", html_body, "no unsubscribe link in the footer")
        code = unquote(html_body.split("code=")[1].split('"')[0])
        service.unsubscribe(code)
        self.assertEqual(
            EmailOptOut.filter_opted_out(["good@example.com"]), {"good@example.com"}
        )


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PRODUCTION=False,
)
class SendTransactionalEmailTests(TestCase):
    """`send_transactional_email` ignores opt-outs and adds no unsubscribe."""

    def _send(self, recipients, **overrides):
        kwargs = {
            "recipients": recipients,
            "subject": "Test",
            "email_context": {**BASE_CONTEXT},
            "html_template": TEMPLATE_HTML,
        }
        kwargs.update(overrides)
        return send_transactional_email(**kwargs)

    def test_sends_to_an_opted_out_recipient(self):
        # Arrange: opting out must not block account or payment mail
        EmailOptOut.add("optout@example.com")

        # Act
        self._send(["optout@example.com"])

        # Assert
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["optout@example.com"])

    def test_does_not_set_unsubscribe_headers(self):
        # Act
        self._send(["good@example.com"])

        # Assert: a provider actioning one-click here would break account access
        headers = mail.outbox[0].extra_headers
        self.assertNotIn("List-Unsubscribe", headers)
        self.assertNotIn("List-Unsubscribe-Post", headers)

    def test_does_not_mark_mail_as_bulk(self):
        # Act
        self._send(["good@example.com"])

        # Assert
        self.assertNotIn("Precedence", mail.outbox[0].extra_headers)

    def test_does_not_render_unsubscribe_link(self):
        # Act
        self._send(["good@example.com"])

        # Assert
        html_body = mail.outbox[0].alternatives[0][0]
        self.assertNotIn("Unsubscribe or change", html_body)

    def test_renders_assets_base_url_without_the_caller_supplying_it(self):
        # Act
        self._send(["good@example.com"])

        # Assert
        html_body = mail.outbox[0].alternatives[0][0]
        self.assertIn(f"{settings.ASSETS_BASE_URL}/email_assets/", html_body)
