from django.db import models
from django.db.models import (
    Count,
    Q,
    F
)
from django.contrib.postgres.fields import JSONField
from django.contrib.contenttypes.fields import GenericRelation

from purchase.models import Purchase
from bullet_point.exceptions import BulletPointModelError
from researchhub.lib import CREATED_LOCATIONS

HELP_TEXT_WAS_EDITED = (
    'True if the text was edited after first being created.'
)
HELP_TEXT_IS_PUBLIC = (
    'Hides this bullet point from the public but not creator.'
)
HELP_TEXT_IS_REMOVED = (
    'Hides this bullet point from all.'
)


class BulletPoint(models.Model):
    BULLETPOINT_KEYTAKEAWAY = 'KEY_TAKEAWAY'
    BULLETPOINT_LIMITATION = 'LIMITATION'
    BULLETPOINT_CHOICES = [
        (BULLETPOINT_KEYTAKEAWAY, BULLETPOINT_KEYTAKEAWAY),
        (BULLETPOINT_LIMITATION, BULLETPOINT_LIMITATION)
    ]
    CREATED_LOCATION_PROGRESS = CREATED_LOCATIONS['PROGRESS']
    CREATED_LOCATION_CHOICES = [
        (CREATED_LOCATION_PROGRESS, CREATED_LOCATION_PROGRESS)
    ]
    paper = models.ForeignKey(
        'paper.Paper',
        on_delete=models.SET_NULL,
        related_name='bullet_points',
        null=True
    )
    created_by = models.ForeignKey(
        'user.User',
        on_delete=models.SET_NULL,
        related_name='bullet_points',
        null=True
    )
    is_head = models.BooleanField(default=True)
    is_tail = models.BooleanField(default=True)
    tail = models.ForeignKey(
        'self',
        default=None,
        null=True,
        blank=True,
        related_name='is_tail_for',
        on_delete=models.SET_NULL
    )
    previous = models.OneToOneField(
        'self',
        default=None,
        null=True,
        blank=True,
        related_name='next',
        on_delete=models.SET_NULL
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    created_location = models.CharField(
        choices=CREATED_LOCATION_CHOICES,
        max_length=255,
        default=None,
        null=True,
        blank=True
    )
    was_edited = models.BooleanField(
        default=False,
        help_text=HELP_TEXT_WAS_EDITED
    )
    is_public = models.BooleanField(
        default=True,
        help_text=HELP_TEXT_IS_PUBLIC
    )
    is_removed = models.BooleanField(
        default=False,
        help_text=HELP_TEXT_IS_REMOVED
    )
    ip_address = models.GenericIPAddressField(
        unpack_ipv4=True,
        blank=True,
        null=True
    )
    purchases = GenericRelation(
        Purchase,
        object_id_field='object_id',
        content_type_field='content_type',
        related_query_name='bulletpoint'
    )
    text = JSONField(blank=True, null=True)
    plain_text = models.TextField(default='', blank=True)
    ordinal = models.IntegerField(default=None, null=True)
    ordinal_is_locked = models.BooleanField(default=False)
    bullet_type = models.CharField(choices=BULLETPOINT_CHOICES, max_length=16)
    actions = GenericRelation(
        'user.Action',
        object_id_field='object_id',
        content_type_field='content_type',
        related_query_name='bullet_point'
    )

    def __str__(self):
        return '%s: %s' % (self.created_by, self.plain_text)

    @property
    def editors(self):
        if self.is_tail:
            return [
                bullet_point.created_by
                for bullet_point
                in self.is_tail_for.all()
            ]
        return []

    @property
    def owners(self):
        if self.created_by:
            return [self.created_by] + self.editors
        else:
            return []

    @property
    def users_to_notify(self):
        return self.paper.owners

    def save(self, *args, **kwargs):
        if self.id is None:
            super().save(*args, **kwargs)
            self.set_ordinal(self.ordinal)
        else:
            super().save(*args, **kwargs)

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

    def remove_from_head(self):
        self.is_head = False
        self.set_ordinal_is_locked(False)
        self.set_ordinal(None)
        self.save()

    def set_ordinal(self, next_ordinal):
        if self.ordinal_is_locked:
            raise BulletPointModelError(None, 'Can not set locked ordinal')

        current_ordinal = self.ordinal

        if next_ordinal is None:
            # Moving out
            if current_ordinal is not None:
                BulletPoint.objects.filter(ordinal__gt=current_ordinal).update(
                    ordinal=models.F('ordinal') - 1
                )
            else:
                return  # No need to replace None with None
        elif current_ordinal is None:
            # Moving in
            BulletPoint.objects.filter(ordinal__gte=next_ordinal).update(
                ordinal=models.F('ordinal') + 1
            )
        elif current_ordinal < next_ordinal:
            # Moving down
            BulletPoint.objects.filter(
                models.Q(
                    ordinal__gt=current_ordinal,
                    ordinal__lte=next_ordinal
                )
            ).update(
                ordinal=models.F('ordinal') - 1
            )
        else:
            # Moving up
            BulletPoint.objects.filter(
                models.Q(
                    ordinal__gte=next_ordinal,
                    ordinal__lt=current_ordinal
                )
            ).update(
                ordinal=models.F('ordinal') + 1
            )
        self.ordinal = next_ordinal
        self.save()

    def set_ordinal_is_locked(self, locked):
        self.ordinal_is_locked = locked
        self.save()

    def calculate_score(self, ignore_self_vote=False):
        qs = self.votes.filter(
            created_by__is_suspended=False,
            created_by__probable_spammer=False
        )

        if ignore_self_vote:
            qs = qs.exclude(bulletpoint__created_by=F('created_by'))

        score = qs.aggregate(
            score=Count(
                'id', filter=Q(vote_type=Vote.UPVOTE)
            ) - Count(
                'id', filter=Q(vote_type=Vote.DOWNVOTE)
            )
        ).get('score', 0)
        return score


class Endorsement(models.Model):
    bullet_point = models.ForeignKey(
        BulletPoint,
        on_delete=models.CASCADE,
        related_name='endorsements',
        related_query_name='endorsement'
    )
    created_by = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='bullet_point_endorsements',
        related_query_name='bullet_point_endorsement'
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['bullet_point', 'created_by'],
                name='unique_bullet_point_endorsement'
            )
        ]


class Flag(models.Model):
    bullet_point = models.ForeignKey(
        BulletPoint,
        on_delete=models.CASCADE,
        related_name='flags',
        related_query_name='flag'
    )
    created_by = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='bullet_point_flags',
        related_query_name='bullet_point_flag'
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['bullet_point', 'created_by'],
                name='unique_bullet_point_flag'
            )
        ]


def create_endorsement(user, bullet_point):
    return Endorsement.objects.create(
        bullet_point=bullet_point,
        created_by=user
    )


def create_flag(user, bullet_point, reason):
    return Flag.objects.create(
        bullet_point=bullet_point,
        created_by=user,
        reason=reason
    )


def retrieve_endorsement(user, bullet_point):
    return Endorsement.objects.get(
        bullet_point=bullet_point,
        created_by=user
    )


def retrieve_flag(user, bullet_point):
    return Flag.objects.get(
        bullet_point=bullet_point,
        created_by=user
    )


class Vote(models.Model):
    UPVOTE = 1
    DOWNVOTE = 2
    VOTE_TYPE_CHOICES = [
        (UPVOTE, 'Upvote'),
        (DOWNVOTE, 'Downvote'),
    ]
    bulletpoint = models.ForeignKey(
        BulletPoint,
        on_delete=models.CASCADE,
        related_name='votes',
        related_query_name='vote'
    )
    created_by = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='bulletpoint_votes',
        related_query_name='bulletpoint_vote'
    )
    created_date = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_date = models.DateTimeField(auto_now=True, db_index=True)
    vote_type = models.IntegerField(choices=VOTE_TYPE_CHOICES)
    is_removed = models.BooleanField(default=False, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['bulletpoint', 'created_by'],
                name='unique_bulletpoint_vote'
            )
        ]

    def __str__(self):
        return '{} - {}'.format(self.created_by, self.vote_type)

    @property
    def users_to_notify(self):
        bulletpoint_author = self.bulletpoint.created_by
        return [bulletpoint_author]
