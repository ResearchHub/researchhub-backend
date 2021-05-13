from django.db import models
from django.db.models import (
    Count,
    Q,
    F
)
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.postgres.fields import JSONField
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericRelation

from purchase.models import Purchase
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
    actions = GenericRelation(
        'user.Action',
        object_id_field='object_id',
        content_type_field='content_type',
        related_query_name='summaries'
    )

    purchases = GenericRelation(
        Purchase,
        object_id_field='object_id',
        content_type_field='content_type',
        related_query_name='summary'
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

    def calculate_score(self, ignore_self_vote=False):
        qs = self.votes.filter(
            created_by__is_suspended=False,
            created_by__probable_spammer=False
        )

        if ignore_self_vote:
            qs = qs.exclude(summary__proposed_by=F('created_by'))

        score = qs.aggregate(
            score=Count(
                'id', filter=Q(vote_type=Vote.UPVOTE)
            ) - Count(
                'id', filter=Q(vote_type=Vote.DOWNVOTE)
            )
        ).get('score', 0)
        return score

    def get_promoted_score(self):
        purchases = self.purchases.filter(
            paid_status=Purchase.PAID,
        )
        if purchases.exists():
            boost_score = sum(
                map(int, purchases.values_list('amount', flat=True))
            )
            return boost_score
        return False


class Vote(models.Model):
    UPVOTE = 1
    DOWNVOTE = 2
    VOTE_TYPE_CHOICES = [
        (UPVOTE, 'Upvote'),
        (DOWNVOTE, 'Downvote'),
    ]
    summary = models.ForeignKey(
        Summary,
        on_delete=models.CASCADE,
        related_name='votes',
        related_query_name='vote'
    )
    created_by = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='summary_votes',
        related_query_name='summary_vote'
    )
    created_date = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_date = models.DateTimeField(auto_now=True, db_index=True)
    vote_type = models.IntegerField(choices=VOTE_TYPE_CHOICES)
    is_removed = models.BooleanField(default=False, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['summary', 'created_by'],
                name='unique_summary_vote'
            )
        ]

    def __str__(self):
        return '{} - {}'.format(self.created_by, self.vote_type)

    @property
    def users_to_notify(self):
        summary_author = self.summary.proposed_by
        return [summary_author]
