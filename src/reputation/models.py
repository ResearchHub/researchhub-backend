from django.db import models

from user.models import User
from .distributions import CreatePaper


class Distribution(models.Model):
    DISTRIBUTION_TYPE_CHOICES = [
        (CreatePaper.name, CreatePaper.name),
    ]

    recipient = models.ForeignKey(
        User,
        related_name='reputation_records',
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )
    amount = models.IntegerField(default=0)
    created_date = models.DateTimeField(auto_now_add=True)
    distribution_type = models.CharField(
        max_length=255,
        choices=DISTRIBUTION_TYPE_CHOICES
    )
    proof = models.CharField(max_length=255)

    def __str__(self):
        return (
            f'Distribution: {self.distribution_type},'
            f' Recipient: {self.recipient},'
            f' Amount: {self.amount}'
        )
