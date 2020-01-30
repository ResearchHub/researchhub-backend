from django.db import models
from django.contrib.postgres.fields import JSONField
from django.utils import timezone


class Summary(models.Model):
    summary = JSONField(default=None, null=True)
    summary_plain_text = models.TextField()
    proposed_by = models.ForeignKey(
        'user.User',
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
        'user.User',
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
    def proposed_by_indexing(self):
        return (
            f'{self.proposed_by.author_profile.first_name}'
            f' {self.proposed_by.author_profile.last_name}'
        )
