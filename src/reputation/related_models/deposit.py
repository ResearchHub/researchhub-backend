from django.db import models

from reputation.related_models.paid_status_mixin import PaidStatusModelMixin
from utils.models import SoftDeletableModel


class Deposit(SoftDeletableModel, PaidStatusModelMixin):
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
    network = models.CharField(
        max_length=10,
        choices=[("BASE", "Base"), ("ETHEREUM", "Ethereum")],
        db_default="ETHEREUM",
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    transaction_hash = models.CharField(default="", blank=True, max_length=255)
