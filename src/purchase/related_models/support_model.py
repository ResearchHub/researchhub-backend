from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import JSONField


class Support(models.Model):
    PAYPAL = "PAYPAL"
    ETH = "ETH"
    BTC = "BTC"
    RSC_ON_CHAIN = "RSC_ON_CHAIN"
    RSC_OFF_CHAIN = "RSC_OFF_CHAIN"

    SINGLE = "SINGLE"
    MONTHLY = "MONTHLY"

    payment_type_choices = [
        (PAYPAL, PAYPAL),
        (ETH, ETH),
        (BTC, BTC),
        (RSC_ON_CHAIN, RSC_ON_CHAIN),
        (RSC_OFF_CHAIN, RSC_OFF_CHAIN),
    ]

    duration_choices = [(SINGLE, SINGLE), (MONTHLY, MONTHLY)]

    sender = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="supported_works"
    )
    recipient = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="supported_by"
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey("content_type", "object_id")
    payment_type = models.CharField(choices=payment_type_choices, max_length=16)
    duration = models.CharField(choices=duration_choices, max_length=8)
    amount = models.CharField(max_length=255)
    proof = JSONField(null=True)
