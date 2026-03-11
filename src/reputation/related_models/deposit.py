import logging

from django.db import models, transaction

from reputation.related_models.paid_status_mixin import PaidStatusModelMixin
from utils.models import SoftDeletableModel

logger = logging.getLogger(__name__)


class Deposit(SoftDeletableModel, PaidStatusModelMixin):
    SWEEP_PENDING = "PENDING"
    SWEEP_INITIATED = "INITIATED"
    SWEEP_COMPLETED = "COMPLETED"
    SWEEP_FAILED = "FAILED"
    SWEEP_STATUS_CHOICES = [
        (SWEEP_PENDING, "Pending"),
        (SWEEP_INITIATED, "Initiated"),
        (SWEEP_COMPLETED, "Completed"),
        (SWEEP_FAILED, "Failed"),
    ]

    CIRCLE_INITIATED = "INITIATED"
    CIRCLE_CONFIRMED = "CONFIRMED"
    CIRCLE_COMPLETED = "COMPLETED"
    CIRCLE_FAILED = "FAILED"
    CIRCLE_STATUS_CHOICES = [
        (CIRCLE_INITIATED, "Initiated"),
        (CIRCLE_CONFIRMED, "Confirmed"),
        (CIRCLE_COMPLETED, "Completed"),
        (CIRCLE_FAILED, "Failed"),
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
        blank=True,
        default="",
    )
    sweep_transfer_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
    )
    circle_status = models.CharField(
        max_length=20,
        choices=CIRCLE_STATUS_CHOICES,
        blank=True,
        default="",
    )

    # Ordering so we only advance circle_status forward, never backwards.
    CIRCLE_STATUS_ORDER = {
        "INITIATED": 0,
        "CONFIRMED": 1,
        "COMPLETED": 2,
        "FAILED": 2,
    }

    class Meta:
        indexes = [
            models.Index(fields=["user", "paid_status"]),
        ]

    @classmethod
    def upsert_pending(
        cls,
        circle_transaction_id,
        wallet,
        amount,
        network,
        circle_status,
        from_address="",
        transaction_hash="",
    ):
        """
        Create or update a pending Deposit for an in-progress Circle transaction.

        If a Deposit with the given ``circle_transaction_id`` already exists, its
        ``circle_status`` is advanced forward but never moved backwards.
        The user is NOT credited at this stage.

        Returns the Deposit instance.
        """
        user = wallet.user

        with transaction.atomic():
            deposit, created = cls.objects.get_or_create(
                circle_transaction_id=circle_transaction_id,
                defaults={
                    "user": user,
                    "amount": amount,
                    "network": network,
                    "from_address": from_address,
                    "transaction_hash": transaction_hash,
                    "paid_status": cls.PENDING,
                    "circle_status": circle_status,
                },
            )

            if not created:
                current_order = cls.CIRCLE_STATUS_ORDER.get(deposit.circle_status, -1)
                new_order = cls.CIRCLE_STATUS_ORDER.get(circle_status, -1)
                if new_order > current_order:
                    deposit.circle_status = circle_status
                    deposit.save(update_fields=["circle_status"])

        if created:
            logger.info(
                "Pending Circle deposit created: user=%s amount=%s network=%s "
                "circle_status=%s circle_transaction_id=%s",
                user.id,
                amount,
                network,
                circle_status,
                circle_transaction_id,
            )
        else:
            logger.info(
                "Circle deposit updated: circle_transaction_id=%s circle_status=%s",
                circle_transaction_id,
                circle_status,
            )

        return deposit
