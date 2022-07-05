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


def get_current_term():
    from reputation.related_models.term import Term

    RH_PCT = 0.01
    DAO_PCT = 0.01

    term = Term.objects.last()
    if term:
        return term.id
    term = Term.objects.create(rh_pct=RH_PCT, dao_pct=DAO_PCT)
    return term.id


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
    recipient = models.ForeignKey(
        "user.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="target_escrows",
    )
    created_by = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="created_escrows"
    )

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey(
        "content_type",
        "object_id",
    )
    status = models.CharField(choices=status_choices, default=PENDING, max_length=16)
    term = models.ForeignKey(
        "reputation.term", on_delete=models.CASCADE, default=get_current_term
    )
