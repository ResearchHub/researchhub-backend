from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import JSONField
from django.db import models
from django.utils import timezone

import ethereum.lib
import reputation.distributions as distributions
from hub.models import Hub
from utils.models import SoftDeletableModel


class PaidStatusModelMixin(models.Model):
    FAILED = "FAILED"
    PAID = "PAID"
    PENDING = "PENDING"
    PAID_STATUS_CHOICES = [
        (FAILED, FAILED),
        (PAID, PAID),
        (PENDING, PENDING),
    ]

    class Meta:
        abstract = True

    paid_date = models.DateTimeField(default=None, null=True)
    paid_status = models.CharField(
        max_length=255, choices=PAID_STATUS_CHOICES, default=None, null=True
    )

    def set_paid_failed(self):
        self.paid_status = self.FAILED
        self.save()

    def set_paid_pending(self):
        self.paid_status = self.PENDING
        self.save()

    def set_paid(self):
        self.paid_status = self.PAID
        self.paid_date = timezone.now()
        self.save()


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
        return "{} {} - {} RSC".format(author.first_name, author.last_name, self.amount)


class Distribution(SoftDeletableModel, PaidStatusModelMixin):
    DISTRIBUTION_TYPE_CHOICES = distributions.DISTRIBUTION_TYPE_CHOICES

    FAILED = "FAILED"
    DISTRIBUTED = "DISTRIBUTED"
    PENDING = "PENDING"
    DISTRIBUTED_STATUS_CHOICES = [
        (FAILED, FAILED),
        (DISTRIBUTED, DISTRIBUTED),
        (PENDING, PENDING),
    ]

    recipient = models.ForeignKey(
        "user.User",
        related_name="reputation_records",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    giver = models.ForeignKey(
        "user.User",
        related_name="reputation_handed_out",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    hubs = models.ManyToManyField(
        Hub,
        related_name="reputation_records",
    )
    amount = models.BigIntegerField(default=0)  # RSC Amount
    reputation_amount = models.IntegerField(default=0)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    distribution_type = models.CharField(
        max_length=255, choices=DISTRIBUTION_TYPE_CHOICES
    )
    proof_item_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True
    )
    proof_item_object_id = models.PositiveIntegerField(null=True)
    proof_item = GenericForeignKey(
        "proof_item_content_type",
        "proof_item_object_id",
    )
    proof = JSONField(null=True)
    distributed_date = models.DateTimeField(default=None, null=True)
    distributed_status = models.CharField(
        max_length=255, choices=DISTRIBUTED_STATUS_CHOICES, default=None, null=True
    )
    withdrawal = models.ForeignKey(
        "reputation.Withdrawal", on_delete=models.CASCADE, default=None, null=True
    )

    def __str__(self):
        return (
            f"Distribution: {self.distribution_type},"
            f" Recipient: {self.recipient},"
            f" Amount: {self.amount}"
        )

    def set_distributed_failed(self):
        self.distributed_status = self.FAILED
        self.save()

    def set_distributed_pending(self):
        self.distributed_status = self.PENDING
        self.save()

    def set_distributed(self):
        self.distributed_status = self.DISTRIBUTED
        self.distributed_date = timezone.now()
        self.save()

    def set_withdrawal(self, withdrawal_instance):
        self.withdrawal = withdrawal_instance
        self.save()


class Webhook(models.Model):
    body = JSONField(blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    from_host = models.CharField(max_length=64, blank=True)


class Deposit(SoftDeletableModel, PaidStatusModelMixin):
    user = models.ForeignKey(
        "user.User", related_name="deposits", on_delete=models.SET_NULL, null=True
    )
    amount = models.CharField(max_length=255, default="0.0")
    from_address = models.CharField(max_length=255)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    transaction_hash = models.CharField(default="", blank=True, max_length=255)


class Withdrawal(SoftDeletableModel, PaidStatusModelMixin):
    TOKEN_ADDRESS_CHOICES = ethereum.lib.TOKEN_ADDRESS_CHOICES

    user = models.ForeignKey(
        "user.User", related_name="withdrawals", on_delete=models.SET_NULL, null=True
    )
    token_address = models.CharField(
        max_length=255,
    )
    amount = models.CharField(max_length=255, default="0.0")
    fee = models.CharField(max_length=255, default="0.0")
    from_address = models.CharField(max_length=255)
    to_address = models.CharField(max_length=255)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    transaction_hash = models.CharField(null=True, blank=True, max_length=255)
    paid_status = models.CharField(
        max_length=255,
        choices=PaidStatusModelMixin.PAID_STATUS_CHOICES,
        default=PaidStatusModelMixin.PENDING,
    )

    class Meta:
        ordering = ["-updated_date"]

    @property
    def users_to_notify(self):
        return [self.user]


class DistributionAmount(models.Model):
    created_date = models.DateTimeField(auto_now_add=True)
    distributed_date = models.DateTimeField(auto_now=True)
    amount = models.IntegerField(default=1000000)
    distributed = models.BooleanField(default=False)


class Contribution(models.Model):
    # PAPER = 'PAPER'
    SUBMITTER = "SUBMITTER"
    UPVOTER = "UPVOTER"
    AUTHOR = "AUTHOR"
    CURATOR = "CURATOR"
    COMMENTER = "COMMENTER"
    SUPPORTER = "SUPPORTER"
    VIEWER = "VIEWER"
    PEER_REVIEWER = "PEER_REVIEWER"

    contribution_choices = [
        # (PAPER, PAPER),
        (AUTHOR, AUTHOR),
        (SUBMITTER, SUBMITTER),
        (UPVOTER, UPVOTER),
        (CURATOR, CURATOR),
        (COMMENTER, COMMENTER),
        (SUPPORTER, SUPPORTER),
        (VIEWER, VIEWER),
        (PEER_REVIEWER, PEER_REVIEWER),
    ]

    contribution_type = models.CharField(max_length=16, choices=contribution_choices)
    user = models.ForeignKey(
        "user.User", related_name="contributions", on_delete=models.SET_NULL, null=True
    )
    unified_document = models.ForeignKey(
        "researchhub_document.ResearchhubUnifiedDocument",
        related_name="contributions",
        on_delete=models.SET_NULL,
        null=True,
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True)
    ordinal = models.PositiveIntegerField()
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey(
        "content_type",
        "object_id",
    )

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Contribution: {} - {}".format(self.id, self.contribution_type)
