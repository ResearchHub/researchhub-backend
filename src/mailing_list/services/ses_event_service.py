from collections.abc import Iterator

from mailing_list.models import EmailRecipient


class SesEventService:
    """
    Processes SES events and updates email delivery preferences accordingly.
    Bounces and complaints are handled by suppressing the affected email addresses.
    """

    def handle_bounce(self, bounce_obj: dict) -> None:
        """
        Suppress recipients of permanent bounces.

        Transient bounces (full mailbox, throttling) are ignored.
        """
        if bounce_obj.get("bounceType") != "Permanent":
            return

        entries = bounce_obj.get("bouncedRecipients", [])

        for recipient in self._recipients(entries):
            recipient.bounced()

    def handle_complaint(self, complaint_obj: dict) -> None:
        """
        Suppress every recipient that reported mail as spam.
        """
        entries = complaint_obj.get("complainedRecipients", [])

        for recipient in self._recipients(entries):
            recipient.do_not_email = True
            recipient.save(update_fields=["do_not_email", "updated_date"])

    def _recipients(self, entries: list[dict]) -> Iterator[EmailRecipient]:
        """
        Yield a recipient row per address, creating the missing ones.
        """
        for entry in entries:
            email = (entry.get("emailAddress") or "").strip()
            if not email:
                continue

            # SES echoes back whatever case the message used, so match
            # case-insensitively rather than adding a row for the same mailbox.
            recipient = EmailRecipient.objects.filter(email__iexact=email).first()
            if recipient is None:
                recipient, _ = EmailRecipient.objects.get_or_create(email=email)

            yield recipient
