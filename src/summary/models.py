from django.db import models
from django.contrib.postgres.fields import JSONField
from django.utils import timezone

from researchhub.lib import CREATED_LOCATIONS


class Summary(models.Model):
    CREATED_LOCATION_PROGRESS = CREATED_LOCATIONS['PROGRESS']
    CREATED_LOCATION_CHOICES = [
        (CREATED_LOCATION_PROGRESS, 'Progress')
    ]

    summary = JSONField(default=None, null=True)
    summary_plain_text = models.TextField()
    proposed_by = models.ForeignKey(
        'user.User',
        null=True,
        blank=True,
        related_name='edits',
        on_delete=models.SET_NULL
    )
    previous = models.ForeignKey(
        'self',
        default=None,
        null=True,
        blank=True,
        related_name='next',
        on_delete=models.SET_NULL
    )
    paper = models.ForeignKey(
        'paper.Paper',
        related_name='summaries',
        on_delete=models.CASCADE
    )
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        'user.User',
        default=None,
        null=True,
        blank=True,
        related_name='approved',
        on_delete=models.SET_NULL
    )
    approved_date = models.DateTimeField(default=None, null=True, blank=True)
    is_removed = models.BooleanField(default=False)

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    created_location = models.CharField(
        choices=CREATED_LOCATION_CHOICES,
        max_length=255,
        default=None,
        null=True,
        blank=True
    )

    def __str__(self):
        return 'Summary: {}, Paper: {}'.format(self.id, self.paper.title)

    @property
    def is_first_paper_summary(self):
        if (
            self.approved
            and (self.previous is None)
            and (self.paper is not None)
        ):
            return len(self.paper.summaries.all()) == 1
        else:
            return False

    def approve(self, by):
        self.approved = True
        self.approved_by = by
        self.approved_date = timezone.now()
        self.save(update_fields=['approved', 'approved_by', 'approved_date'])

    @property
    def paper_indexing(self):
        return self.paper.id

    @property
    def paper_title_indexing(self):
        return self.paper.title

    @property
    def users_to_notify(self):
        if self.paper:
            return self.paper.users_to_notify
        return []

    @property
    def proposed_by_indexing(self):
        return (
            f'{self.proposed_by.author_profile.first_name}'
            f' {self.proposed_by.author_profile.last_name}'
        )
