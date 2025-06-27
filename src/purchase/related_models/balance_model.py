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

    # TODO: why is this a char field?
    amount = models.CharField(max_length=255)
    testnet_amount = models.CharField(max_length=255, default=0, null=True, blank=True)

    # Balance locking fields
    is_locked = models.BooleanField(default=False)
    lock_type = models.TextField(
        choices=[
            ("REFERRAL_BONUS", "Referral Bonus"),
        ],
        null=True,
        blank=True,
    )

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
