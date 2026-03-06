from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from utils.models import DefaultModel


class PaymentProcessor(models.TextChoices):
    STRIPE = "STRIPE", _("Stripe")


class PaymentPurpose(models.TextChoices):
    """
    The purpose of the payment, such as an APC or an RSC purchase.
    """

    APC = "APC", _("Article Processing Charge")
    RSC_PURCHASE = "RSC_PURCHASE", _("RSC Purchase")
    FUNDING_CREDITS = "FUNDING_CREDITS", _("Funding Credits")


class PaymentMethodType(models.TextChoices):
    """
    The payment method used for the transaction.
    """

    CARD = "CARD", _("Card")
    ACH = "ACH", _("ACH Bank Transfer")


class PaymentStatus(models.TextChoices):
    """
    Status of the payment.
    """

    FAILED = "FAILED", _("Failed")
    PROCESSING = "PROCESSING", _("Processing")
    SUCCEEDED = "SUCCEEDED", _("Succeeded")


class Payment(DefaultModel):
    """
    Model to store details of payments made via a payment processor.
    """

    amount = models.IntegerField(null=False, blank=False)
    currency = models.CharField(max_length=3, null=False, blank=False)
    external_payment_id = models.TextField(null=False, blank=False)
    payment_processor = models.TextField(
        choices=PaymentProcessor.choices, null=False, blank=False
    )
    purpose = models.TextField(
        choices=PaymentPurpose.choices,
        null=False,
        blank=False,
        default=PaymentPurpose.APC,  # FIXME: Remove default after migration
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey("content_type", "object_id")
    user = models.ForeignKey(
        "user.User",
        related_name="payments",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    payment_method_type = models.TextField(
        choices=PaymentMethodType.choices,
    )
    status = models.TextField(
        choices=PaymentStatus.choices,
    )
    failure_reason = models.TextField(null=True, blank=True)
