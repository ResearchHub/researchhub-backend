from decimal import Decimal

from django.template.loader import render_to_string

from mailing_list.services import EMAIL_PREVIEW_LENGTH, EmailService
from notification.models import Notification
from notification.services import NotificationService
from purchase.related_models.constants.currency import USD
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.models import Bounty, BountySolution, Escrow
from researchhub_comment.services.comment_html_service import render_comment_html
from researchhub_document.services.work_cover_service_for_email import (
    build_work_cover,
    format_compact_usd,
)
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
        self,
        escrow_id: int,
        recipient_id: int,
        payout_amount: Decimal,
        solution_id: int | None = None,
    ) -> None:
        """Send the recipient an in-app alert and an email after a payout commits."""
        escrow = Escrow.objects.select_related("created_by").get(id=escrow_id)
        recipient = User.objects.select_related("author_profile").get(id=recipient_id)
        item = escrow.item
        unified_document = item.unified_document

        if escrow.hold_type == Escrow.BOUNTY:
            notification_type = Notification.BOUNTY_PAYOUT
            subject = (
                f"Congratulations {recipient.first_name}, you were awarded a bounty!"
            )
            body = (
                render_comment_html(
                    BountySolution.objects.get(id=solution_id).item,
                    max_length=EMAIL_PREVIEW_LENGTH,
                )
                if solution_id
                else None
            )
            card = {
                "author": recipient.author_profile,
                "action": "Earned",
                "amount": format_compact_usd(
                    RscExchangeRate.rsc_to_usd(float(payout_amount))
                ),
                "action_trailing": (
                    "for a peer review"
                    if escrow.bounties.first().bounty_type == Bounty.Type.REVIEW
                    else None
                ),
                "body": body,
            }
            link = f"{unified_document.frontend_view_link()}/bounties"
        else:
            notification_type = Notification.FUNDRAISE_PAYOUT
            subject = (
                f"Congratulations {recipient.first_name}, your proposal is fully "
                "funded!"
            )
            card = {
                "author": item.created_by.author_profile,
                "action": "Raised",
                "amount": format_compact_usd(item.get_amount_raised(currency=USD)),
                "action_trailing": "for a proposal",
            }
            link = unified_document.frontend_view_link()

        self._notifications.try_send(
            notification_type,
            recipient=recipient,
            action_user=escrow.created_by,
            item=escrow,
            unified_document=unified_document,
            extra={"amount": str(payout_amount)},
        )
        message = render_to_string(
            "email_activity_card.html",
            {
                **card,
                "created_date": escrow.updated_date,
                "cover": build_work_cover(unified_document.get_document()),
            },
        )
        self._emails.send_message_email(
            [recipient.email], subject, message, link=link, is_html=True
        )
