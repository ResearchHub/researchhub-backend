from decimal import Decimal

from mailing_list.services import EmailService
from notification.models import Notification
from notification.services import NotificationService
from reputation.models import Escrow
from user.models import User


class EscrowPayoutNotificationService:
    """Notify users when a bounty or fundraise escrow pays out to them."""

    def __init__(
        self,
        notification_service: NotificationService | None = None,
        email_service: EmailService | None = None,
    ) -> None:
        """Configure notification and email delivery for escrow payouts."""
        self._notifications = notification_service or NotificationService()
        self._emails = email_service or EmailService()

    def notify_payout_recipient(
        self, escrow_id: int, recipient_id: int, payout_amount: Decimal
    ) -> None:
        """Send the recipient an in-app alert and an email after a payout commits."""
        escrow = Escrow.objects.select_related("created_by").get(id=escrow_id)
        recipient = User.objects.get(id=recipient_id)
        unified_document = escrow.item.unified_document
        title = unified_document.get_display_title()

        if escrow.hold_type == Escrow.BOUNTY:
            notification_type = Notification.BOUNTY_PAYOUT
            subject = "Bounty Payout"
            message = (
                f"{escrow.created_by.full_name()} awarded you a bounty for your "
                f"thread in {title}."
            )
            link = f"{unified_document.frontend_view_link()}/bounties"
        else:
            notification_type = Notification.FUNDRAISE_PAYOUT
            subject = "Fundraise Payout"
            message = (
                f"Congratulations! Your fundraise for {title} has been fulfilled "
                "and paid out to you."
            )
            link = unified_document.frontend_view_link()

        self._notifications.try_send(
            notification_type,
            recipient=recipient,
            action_user=escrow.created_by,
            item=escrow,
            unified_document=unified_document,
            extra={"amount": str(payout_amount)},
        )
        self._emails.send_message_email([recipient.email], subject, message, link=link)
