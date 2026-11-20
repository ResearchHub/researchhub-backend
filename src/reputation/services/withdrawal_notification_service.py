from decimal import Decimal

from mailing_list.services import EmailService
from reputation.models import Withdrawal


class WithdrawalNotificationService:
    """Email users about their withdrawals, regardless of email preferences."""

    def __init__(self, email_service: EmailService | None = None) -> None:
        """Configure email delivery for withdrawals."""
        self._emails = email_service or EmailService()

    def notify_requested(self, withdrawal_id: int) -> None:
        """Email the user once their withdrawal request commits."""
        self._send(
            withdrawal_id,
            "is on its way",
            "If you did not request this withdrawal, "
            "contact ResearchHub support right away.",
        )

    def notify_completed(self, withdrawal_id: int) -> None:
        """Email the user once their withdrawal is confirmed on-chain."""
        self._send(withdrawal_id, "is complete")

    def _send(self, withdrawal_id: int, status: str, note: str | None = None) -> None:
        """Send a transactional email describing the withdrawal."""
        withdrawal = Withdrawal.objects.select_related("user").get(id=withdrawal_id)
        if not withdrawal.user:
            return

        amount = f"{Decimal(withdrawal.amount).normalize():,f} RSC"
        subject = f"Your withdrawal of {amount} {status}"
        lines = [
            f"Amount: {amount}",
            f"Fee: {Decimal(withdrawal.fee).normalize():,f} RSC",
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
