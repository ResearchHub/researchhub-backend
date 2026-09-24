import logging
import re
from time import sleep
from typing import Any

from bs4 import BeautifulSoup
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.template import TemplateDoesNotExist
from django.template.loader import get_template

from mailing_list.models import EmailOptOut
from mailing_list.services.email_subscription_service import EmailSubscriptionService

logger = logging.getLogger(__name__)

DEFAULT_SEND_INTERVAL_SECONDS = 0.2


class EmailService:
    """
    Render and send email through Django's configured backend.
    """

    def __init__(
        self,
        subscription_service: EmailSubscriptionService | None = None,
        sender: str | None = None,
        send_interval_seconds: float = DEFAULT_SEND_INTERVAL_SECONDS,
    ) -> None:
        """Configure subscription handling, the sender, and batch pacing."""
        self._subscriptions = subscription_service or EmailSubscriptionService()
        self._sender = sender or f"ResearchHub <{settings.DEFAULT_FROM_EMAIL}>"
        self._send_interval_seconds = send_interval_seconds

    def send_email(
        self,
        recipients: str | list[str],
        subject: str,
        email_context: dict[str, Any],
        *,
        template: str,
        sender: str | None = None,
        reply_to: str | list[str] | None = None,
        cc: list[str] | None = None,
    ) -> None:
        """
        Send optional email, skipping addresses that have opted out.

        `template` base name of the template without extension.

        This is the standard entry point, and the right default for anything the
        recipient could reasonably not want. Recipients get a signed unsubscribe
        link in the body and a matching `List-Unsubscribe` header. Use
        `send_transactional_email` for mail they must receive regardless of their
        preferences.

        Undeliverable and complained-about addresses are handled separately by the
        SES backend's blacklist, which applies to both methods.
        """
        self._send(
            recipients=recipients,
            template=template,
            subject=subject,
            email_context=email_context,
            sender=sender,
            reply_to=reply_to,
            cc=cc,
            unsubscribable=True,
        )

    def send_transactional_email(
        self,
        recipients: str | list[str],
        subject: str,
        email_context: dict[str, Any],
        *,
        template: str,
        sender: str | None = None,
        reply_to: str | list[str] | None = None,
        cc: list[str] | None = None,
    ) -> None:
        """
        Send transactional email regardless of optional-email preferences.

        `template` base name of the template without extension.

        Transactional emails can include email confirmation, password reset, and
        others. Opting out of optional email must not lock someone out of
        their own account.
        """
        self._send(
            recipients=recipients,
            template=template,
            subject=subject,
            email_context=email_context,
            sender=sender,
            reply_to=reply_to,
            cc=cc,
            unsubscribable=False,
        )

    def send_message_email(
        self,
        recipients: str | list[str],
        subject: str,
        message: str,
        *,
        link: str | None = None,
        heading: str | None = None,
    ) -> None:
        """Send an opt-out-aware message with an optional action link."""
        self.send_email(
            recipients,
            subject,
            {
                "subject": heading or subject,
                "body": message,
                "cta_url": link,
                "preserve_linebreaks": True,
            },
            template="general_branded_email",
        )

    def send_html_email(
        self,
        recipient: str,
        subject: str,
        body: str,
        *,
        sender: str | None = None,
        reply_to: str | list[str] | None = None,
        cc: list[str] | None = None,
    ) -> str | None:
        """Send prepared HTML and return its backend message ID when available.

        Return None when the backend skips the message, or an empty string when
        it sends successfully without providing a message ID.

        Preserve outreach's caller-managed sending policy and propagate failures.
        This path does not apply opt-outs, unsubscribe links, or the recipient
        whitelist. The backend still applies its policy.
        """
        return self._send_message(
            recipient,
            subject,
            body,
            self._html_to_text(body) or "(No content)",
            sender=sender,
            reply_to=reply_to,
            cc=cc,
        )

    def _send(
        self,
        recipients: str | list[str],
        subject: str,
        email_context: dict[str, Any],
        *,
        template: str,
        sender: str | None,
        reply_to: str | list[str] | None,
        cc: list[str] | None,
        unsubscribable: bool,
    ) -> None:
        """
        Render and send one message per recipient.

        Sends are best-effort: a recipient that fails is logged and skipped so one
        bad address cannot abort the rest of the batch.
        """
        if not isinstance(recipients, list):
            recipients = [recipients]

        html_template = get_template(f"{template}.html")
        try:
            text_template = get_template(f"{template}.txt")
        except TemplateDoesNotExist:
            text_template = None

        opted_out = (
            EmailOptOut.filter_opted_out(recipients) if unsubscribable else set()
        )
        subscriptions = self._subscriptions

        for recipient in recipients:
            if recipient in opted_out or not self._is_allowed_recipient(recipient):
                continue

            context = {"assets_base_url": settings.ASSETS_BASE_URL, **email_context}
            headers: dict[str, str] = {}

            if unsubscribable:
                try:
                    opt_out_url = subscriptions.generate_unsubscribe_url(recipient)
                    one_click_url = subscriptions.generate_list_unsubscribe_url(
                        recipient
                    )
                except ValidationError:
                    # If it's not a valid address, there is nothing to unsubscribe
                    logger.warning(
                        "Skipping unsubscribe links for invalid recipient",
                        extra={"recipient": recipient},
                    )
                else:
                    context["opt_out"] = opt_out_url
                    headers["Precedence"] = "bulk"
                    headers["List-Unsubscribe"] = f"<{one_click_url}>"
                    headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

            html_body = html_template.render(context)
            plain_body = (
                text_template.render(context)
                if text_template
                else self._html_to_text(html_body)
            )

            try:
                self._send_message(
                    recipient,
                    subject,
                    html_body,
                    plain_body,
                    sender=sender,
                    reply_to=reply_to,
                    cc=cc,
                    headers=headers,
                )
            except Exception:
                logger.exception("Email send failed to %s", recipient)

            sleep(self._send_interval_seconds)

    def _send_message(
        self,
        recipient: str,
        subject: str,
        html_body: str,
        plain_body: str,
        *,
        sender: str | None,
        reply_to: str | list[str] | None,
        cc: list[str] | None,
        headers: dict[str, str] | None = None,
    ) -> str | None:
        """Send one multipart message, logging and returning None when skipped."""
        subject = subject.replace("\n", "").replace("\r", "")
        if isinstance(reply_to, str):
            reply_to = [reply_to] if reply_to else None
        message = EmailMultiAlternatives(
            subject=subject if settings.PRODUCTION else f"[Staging] {subject}",
            body=plain_body,
            from_email=sender or self._sender,
            to=[recipient],
            reply_to=reply_to,
            cc=cc,
            headers=headers,
        )
        message.attach_alternative(html_body, "text/html")
        if message.send(fail_silently=False) != 1:
            logger.warning("Email backend did not send message to %s", recipient)
            return None
        return message.extra_headers.get("message_id") or ""

    @staticmethod
    def _html_to_text(html: str) -> str:
        """
        Convert HTML to readable plain text: non-text elements dropped, entities
        decoded, links kept as "label (url)", block boundaries as line breaks.
        """
        soup = BeautifulSoup(html, "lxml")

        for element in soup(["head", "script", "style", "title"]):
            element.decompose()

        for a in soup.find_all("a", href=True):
            label = " ".join(a.get_text().split())
            href = a["href"]
            if (
                label
                and href.startswith(("http://", "https://"))  # NOSONAR - Ignore http
                and label != href
            ):
                a.replace_with(f"{label} ({href})")

        # Mark block boundaries with a sentinel that survives whitespace
        # collapsing, so newlines in the HTML source don't become line breaks
        # but element structure does.
        for block in soup.find_all(
            ["br", "div", "h1", "h2", "h3", "h4", "li", "p", "table", "td", "tr"]
        ):
            block.insert(0, "\0")
            block.append("\0")

        # Where the HTML renders whitespace literally, the text's own line
        # breaks are visible content and must survive the collapse below.
        for element in soup.find_all(style=re.compile(r"white-space:\s*pre")):
            for node in element.find_all(string=True):
                node.replace_with(node.replace("\n", "\0"))

        text = " ".join(soup.get_text().split())
        text = re.sub(r" ?\0 ?", "\0", text)
        return re.sub(r"\0{3,}", "\0\0", text).replace("\0", "\n").strip("\n ")

    @staticmethod
    def _is_allowed_recipient(email: str) -> bool:
        """
        Return whether the email is allowed for sending in the current environment.

        An entry starting with `@` whitelists an entire domain, so `@researchhub.com`
        allows every recipient at that domain.
        """
        if settings.TESTING or settings.PRODUCTION:
            return True

        email = email.strip().lower()
        _, _, domain = email.rpartition("@")

        return any(
            entry == email or (entry.startswith("@") and entry[1:] == domain)
            for entry in (e.strip().lower() for e in settings.EMAIL_WHITELIST)
        )
