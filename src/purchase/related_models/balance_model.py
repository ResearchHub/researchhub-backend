from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Balance(models.Model):

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

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

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
