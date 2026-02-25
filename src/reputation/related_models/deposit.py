from django.db import models

from reputation.related_models.paid_status_mixin import PaidStatusModelMixin
from utils.models import SoftDeletableModel


class Deposit(SoftDeletableModel, PaidStatusModelMixin):
    SWEEP_PENDING = "PENDING"
    SWEEP_INITIATED = "INITIATED"
    SWEEP_COMPLETE = "COMPLETE"
    SWEEP_FAILED = "FAILED"
    SWEEP_STATUS_CHOICES = [
        (SWEEP_PENDING, "Pending"),
        (SWEEP_INITIATED, "Initiated"),
        (SWEEP_COMPLETE, "Complete"),
        (SWEEP_FAILED, "Failed"),
    ]

    user = models.ForeignKey(
        "user.User", related_name="deposits", on_delete=models.SET_NULL, null=True
    )
    amount = models.CharField(max_length=255, default="0.0")
    network = models.CharField(
        max_length=10,
        choices=[("BASE", "Base"), ("ETHEREUM", "Ethereum")],
        db_default="ETHEREUM",
    )
    from_address = models.CharField(max_length=255)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    transaction_hash = models.CharField(default="", blank=True, max_length=255)
    circle_transaction_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
    )
    sweep_status = models.CharField(
        max_length=20,
        choices=SWEEP_STATUS_CHOICES,
        null=True,
        blank=True,
    )
    sweep_transfer_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
    )
