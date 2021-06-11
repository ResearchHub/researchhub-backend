from django.db.models import Count, F, Q

from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import (
    GenericForeignKey,
    GenericRelation
)
from django.db import models
from utils.models import DefaultModel


class Vote(models.Model):
    UPVOTE = 1
    DOWNVOTE = 2
    VOTE_TYPE_CHOICES = [
        (UPVOTE, 'Upvote'),
        (DOWNVOTE, 'Downvote'),
    ]
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey('content_type', 'object_id')
    distributions = GenericRelation(
        'reputation.Distribution',
        object_id_field='proof_item_object_id',
        content_type_field='proof_item_content_type'
    )
    created_by = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='discussion_votes'
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    vote_type = models.IntegerField(choices=VOTE_TYPE_CHOICES)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['content_type', 'object_id', 'created_by'],
                name='unique_vote'
            )
        ]

    def __str__(self):
        return '{} - {}'.format(self.created_by, self.vote_type)

    @property
    def paper(self):
        return self.item.paper


class Flag(models.Model):
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey('content_type', 'object_id')
    created_by = models.ForeignKey('user.User', on_delete=models.CASCADE)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['content_type', 'object_id', 'created_by'],
                name='unique_flag'
            )
        ]


class Endorsement(models.Model):
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey('content_type', 'object_id')
    created_by = models.ForeignKey('user.User', on_delete=models.CASCADE)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['content_type', 'object_id'],
                name='unique_endorsement'
            )
        ]


class AbstractGenericReactionModel(DefaultModel):
    endorsement = GenericRelation(Endorsement)
    flags = GenericRelation(Flag)
    vote = GenericRelation(Vote)

    @property
    def score_indexing(self):
        return self.calculate_score()

    def calculate_score(self, ignore_self_vote=False):
        if hasattr(self, 'score'):
            return self.score
        else:
            qs = self.votes.filter(
                created_by__is_suspended=False,
                created_by__probable_spammer=False
            )

            if ignore_self_vote:
                qs = qs.exclude(created_by=F('discussion__created_by'))

            score = qs.aggregate(
                score=Count(
                    'id', filter=Q(vote_type=Vote.UPVOTE)
                ) - Count(
                    'id', filter=Q(vote_type=Vote.DOWNVOTE)
                )
            ).get('score', 0)
            return score

    class Meta:
        abstract = True
