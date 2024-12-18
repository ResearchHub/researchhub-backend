from django.db import models

import ethereum.lib
from reputation.related_models.paid_status_mixin import PaidStatusModelMixin
from utils.models import SoftDeletableModel


class Withdrawal(SoftDeletableModel, PaidStatusModelMixin):
    TOKEN_ADDRESS_CHOICES = ethereum.lib.TOKEN_ADDRESS_CHOICES

    user = models.ForeignKey(
        "user.User", related_name="withdrawals", on_delete=models.SET_NULL, null=True
    )
    token_address = models.CharField(
        max_length=255,
    )
    amount = models.CharField(max_length=255, default="0.0")
    fee = models.CharField(max_length=255, default="0.0")
    from_address = models.CharField(max_length=255)
    to_address = models.CharField(max_length=255)
    network = models.CharField(
        max_length=10,
        choices=[("BASE", "Base"), ("ETHEREUM", "Ethereum")],
        db_default="ETHEREUM",
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    transaction_hash = models.CharField(null=True, blank=True, max_length=255)
    paid_status = models.CharField(
        max_length=255,
        choices=PaidStatusModelMixin.PAID_STATUS_CHOICES,
        default=PaidStatusModelMixin.PENDING,
    )

    class Meta:
        ordering = ["-updated_date"]

    @property
    def users_to_notify(self):
        return [self.user]
