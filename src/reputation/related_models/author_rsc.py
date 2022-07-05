from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from utils.models import DefaultModel


class AuthorRSC(models.Model):
    author = models.ForeignKey(
        "user.Author",
        related_name="author_rsc",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    paper = models.ForeignKey(
        "paper.Paper",
        related_name="author_rsc",
        on_delete=models.CASCADE,
    )
    amount = models.DecimalField(default=0, decimal_places=10, max_digits=19)

    def __str__(self):
        return "{} {} - {} RSC".format(
            self.author.first_name, self.author.last_name, self.amount
        )


class Escrow(DefaultModel):
    BOUNTY = "BOUNTY"
    AUTHOR_RSC = "AUTHOR_RSC"
    hold_type_choices = (
        (BOUNTY, BOUNTY),
        (AUTHOR_RSC, AUTHOR_RSC),
    )

    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"
    status_choices = (
        (PAID, PAID),
        (PARTIALLY_PAID, PARTIALLY_PAID),
        (PENDING, PENDING),
        (CANCELLED, CANCELLED),
    )

    hold_type = models.CharField(choices=hold_type_choices, max_length=16)
    amount = models.DecimalField(default=0, decimal_places=10, max_digits=19)
    recipient_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="user_escrow"
    )
    recipient_object_id = models.PositiveIntegerField()
    recipient = GenericForeignKey(
        "recipient_content_type",
        "recipient_object_id",
    )
    created_by = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="escrows"
    )

    item_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="item_escrow"
    )
    item_object_id = models.PositiveIntegerField()
    item = GenericForeignKey(
        "item_content_type",
        "item_object_id",
    )
    status = models.CharField(choices=status_choices, default=PENDING, max_length=16)
    term = models.ForeignKey("reputation.term", on_delete=models.CASCADE)
