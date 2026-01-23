from django.db import models

from utils.models import DefaultModel


class BalanceEntryDate(DefaultModel):
    """
    Tracks RSC batches with their entry timestamps for FIFO withdrawal handling.
    Each positive Balance record creates a corresponding BalanceEntryDate.

    When a user withdraws RSC, we use FIFO (First In, First Out) to determine
    which balance entries are affected. This means newer RSC is withdrawn first,
    preserving the higher multipliers on older holdings.
    """

    user = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="balance_entry_dates"
    )

    # Link to the Balance record that created this entry
    balance = models.ForeignKey(
        "purchase.Balance",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entry_date_record",
    )

    # Entry date (when RSC entered account)
    entry_date = models.DateTimeField(
        db_index=True,
        help_text="When this RSC batch entered the account",
    )

    # Original amount when RSC entered account
    original_amount = models.DecimalField(
        max_digits=19,
        decimal_places=10,
        help_text="Original amount when RSC entered account",
    )

    # Remaining amount after partial withdrawals (FIFO)
    remaining_amount = models.DecimalField(
        max_digits=19,
        decimal_places=10,
        help_text="Amount remaining after any FIFO withdrawals",
    )

    class Meta:
        indexes = [
            models.Index(fields=["user", "entry_date"]),
            models.Index(fields=["user", "remaining_amount"]),
        ]

    def __str__(self):
        return f"BalanceEntryDate({self.user_id}, {self.entry_date.date()}, {self.remaining_amount})"
