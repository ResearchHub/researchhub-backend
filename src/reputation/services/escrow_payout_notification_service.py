from decimal import Decimal

from django.template.loader import render_to_string

from mailing_list.services import EMAIL_PREVIEW_LENGTH, EmailService, truncate_preview
from notification.models import Notification
from notification.services import NotificationService
from reputation.models import BountySolution, Escrow
from researchhub_comment.services.comment_html_service import render_comment_html
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
            subject = (
                f"Congratulations {recipient.first_name}, you were awarded a bounty!"
            )
            answer = (
                BountySolution.objects.filter(
                    bounty__escrow=escrow,
                    created_by=recipient,
                    status=BountySolution.Status.AWARDED,
                )
                .latest("updated_date")
                .item
            )
            card = {
                "author": recipient.author_profile,
                "action": "Answer",
                "created_date": answer.created_date,
                "body": render_comment_html(answer, max_length=EMAIL_PREVIEW_LENGTH),
            }
            link = f"{unified_document.frontend_view_link()}/bounties"
        else:
            notification_type = Notification.FUNDRAISE_PAYOUT
            subject = (
                f"Congratulations {recipient.first_name}, your proposal is fully "
                "funded!"
            )
            proposal = unified_document.get_document()
            card = {
                "author": proposal.created_by.author_profile,
                "action": "Proposal",
                "created_date": proposal.created_date,
                "body": truncate_preview(proposal.renderable_text),
            }
            link = unified_document.frontend_view_link()

        message = render_to_string(
            "email_content_card.html", {**card, "title": title, "possessive": True}
        )
        self._notifications.try_send(
            notification_type,
            recipient=recipient,
            action_user=escrow.created_by,
            item=escrow,
            unified_document=unified_document,
            extra={"amount": str(payout_amount)},
        )
        self._emails.send_message_email(
            [recipient.email], subject, message, link=link, is_html=True
        )
