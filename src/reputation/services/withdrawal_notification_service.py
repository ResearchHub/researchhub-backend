from decimal import Decimal

from mailing_list.services import EmailService
from reputation.models import Withdrawal
from reputation.related_models.paid_status_mixin import PaidStatusModelMixin

# Subject ending and closing note for each status a user is told about.
MESSAGES = {
    PaidStatusModelMixin.INITIATED: (
        "is on its way",
        (
            "If you did not request this withdrawal, contact ResearchHub support "
            "right away and quote the withdrawal number above."
        ),
    ),
    PaidStatusModelMixin.PAID: ("is complete", None),
    PaidStatusModelMixin.FAILED: (
        "failed",
        "The transfer did not go through and your RSC has been returned.",
    ),
}


class WithdrawalNotificationService:
    """Email users about their withdrawals, regardless of email preferences."""

    def __init__(self, email_service: EmailService | None = None) -> None:
        """Configure email delivery for withdrawals."""
        self._emails = email_service or EmailService()

    def notify(self, withdrawal_id: int, paid_status: str) -> None:
        """Email the user that their withdrawal reached the given status."""
        withdrawal = Withdrawal.objects.select_related("user").get(id=withdrawal_id)
        if not withdrawal.user:
            return

        status, note = MESSAGES[paid_status]
        amount, fee = Decimal(withdrawal.amount), Decimal(withdrawal.fee)
        subject = f"Your withdrawal of {amount.normalize():,f} RSC {status}"
        lines = [
            f"Withdrawal: #{withdrawal.id}",
            f"Amount sent: {amount.normalize():,f} RSC",
            f"Fee: {fee.normalize():,f} RSC",
            f"Total: {(amount + fee).normalize():,f} RSC",
            f"Network: {withdrawal.get_network_display()}",
            f"To: {withdrawal.to_address}",
        ]
        if withdrawal.transaction_hash:
            lines.append(f"Transaction: {withdrawal.transaction_hash}")
        if note:
            lines += ["", note]

        self._emails.send_transactional_email(
            [withdrawal.user.email],
            subject,
            {
                "subject": subject,
                "body": "\n".join(lines),
                "preserve_linebreaks": True,
            },
            template="general_branded_email",
        )
