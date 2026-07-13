from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Balance(models.Model):
    class LockType(models.TextChoices):
        # Non-promotional locked RSC — spendable on fundraises, no yield.
        # The source Distribution retains provenance such as PURCHASE,
        # REFERRAL_BONUS, or STAKING_YIELD.
        FUNDING_CREDIT = "FUNDING_CREDIT", "Funding Credit"
        # Promotional grants — not withdrawable, but earn staking yield.
        PROMOTIONAL = "PROMOTIONAL", "Promotional"

    # Order in which locked categories are consumed when spending. Promotional
    # funds earn yield, so they are consumed last. Debits are written per
    # category so refunds can restore each category exactly.
    LOCKED_SPEND_ORDER = (
        LockType.FUNDING_CREDIT,
        LockType.PROMOTIONAL,
    )

    user = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="balances"
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField(null=True)
    source = GenericForeignKey("content_type", "object_id")

    # Optional link to the purchase that triggered this balance record.
    # Used for contribution refunds.
    purchase = models.ForeignKey(
        "purchase.Purchase",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="balance_records",
    )

    # TODO: why is this a char field?
    amount = models.CharField(max_length=255)
    testnet_amount = models.CharField(max_length=255, default=0, null=True, blank=True)

    is_locked = models.BooleanField(default=False)

    # Sub-categorizes locked funds (is_locked=True). `is_locked` alone decides
    # withdrawability; `lock_type` decides category-specific behavior, e.g.
    # PROMOTIONAL funds earn staking yield while other locked funds do not.
    lock_type = models.TextField(choices=LockType.choices, null=True, blank=True)

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        is_locked=True,
                        lock_type__isnull=False,
                        lock_type__in=("FUNDING_CREDIT", "PROMOTIONAL"),
                    )
                    | models.Q(is_locked=False, lock_type__isnull=True)
                ),
                name="balance_lock_state_valid",
            ),
        ]
        indexes = [
            # Partial index: the vast majority of rows are unlocked with a
            # NULL lock_type, so only index the categorized (locked) rows.
            models.Index(
                fields=["lock_type"],
                name="balance_lock_type_idx",
                condition=models.Q(lock_type__isnull=False),
            ),
        ]

    def save(self, *args, **kwargs):
        """Keep lock state valid before the database constraint is reached."""
        original_lock_type = self.lock_type

        if self.is_locked:
            # All non-promotional locked funds have the same behavior, so make
            # that safe behavior the default for older/internal callers.
            if self.lock_type in (None, ""):
                self.lock_type = self.LockType.FUNDING_CREDIT
            elif self.lock_type not in self.LockType.values:
                raise ValueError(f"Unsupported balance lock type: {self.lock_type}")
        elif self.lock_type is not None:
            raise ValueError("Unlocked balances cannot have a lock type")

        update_fields = kwargs.get("update_fields")
        if update_fields is not None and self.lock_type != original_lock_type:
            kwargs["update_fields"] = {*update_fields, "lock_type"}

        return super().save(*args, **kwargs)

    @staticmethod
    def locked_by_referral_bonus(queryset=None):
        from reputation.models import Distribution

        qs = queryset if queryset is not None else Balance.objects.all()
        dist_ct = ContentType.objects.get_for_model(Distribution)
        return qs.filter(
            is_locked=True,
            content_type=dist_ct,
            object_id__in=Distribution.objects.filter(
                distribution_type="REFERRAL_BONUS"
            ).values_list("id", flat=True),
        )
