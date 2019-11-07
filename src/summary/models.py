from django.db import models
from django.contrib.postgres.fields import JSONField
from django.utils import timezone

from user.models import User


class Summary(models.Model):
    summary = JSONField(default=None, null=True)
    summary_plain_text = models.TextField()
    proposed_by = models.ForeignKey(
        User,
        related_name='edits',
        on_delete='SET NULL'
    )
    previous = models.ForeignKey(
        'self',
        default=None,
        null=True,
        blank=True,
        related_name='next',
        on_delete='SET NULL'
    )
    paper = models.ForeignKey(
        'paper.Paper',
        related_name='summaries',
        on_delete='CASCADE'
    )
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        User,
        default=None,
        null=True,
        blank=True,
        related_name='approved',
        on_delete='SET NULL'
    )
    approved_date = models.DateTimeField(default=None, null=True, blank=True)

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.id

    def approve(self, by):
        self.approved = True
        self.approved_by = by
        self.approved_date = timezone.now()
        self.save()

    @property
    def summary_indexing(self):
        return str(self.summary)
