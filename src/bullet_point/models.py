from django.contrib.postgres.fields import JSONField
from django.db import models

from bullet_point.exceptions import BulletPointModelError

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
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
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
    text = JSONField(blank=True, null=True)
    plain_text = models.TextField(default='', blank=True)
    ordinal = models.IntegerField(default=None, null=True)
    ordinal_is_locked = models.BooleanField(default=False)

    def __str__(self):
        return '%s: %s' % (self.created_by, self.plain_text)

    @property
    def owners(self):
        if self.created_by:
            return [self.created_by]
        else:
            return []

    @property
    def users_to_notify(self):
        return self.paper.owners

    def set_ordinal(self, ordinal):
        if self.ordinal_is_locked:
            raise BulletPointModelError(None, 'Can not set locked ordinal')

        offset = 1
        if ordinal is None:
            if self.ordinal is not None:
                offset = -1
            else:
                return  # No need to replace None with None

        BulletPoint.objects.filter(ordinal__gt=ordinal).update(
            ordinal=models.F('ordinal') + offset
        )
        self.ordinal = ordinal
        self.save()

    def set_ordinal_is_locked(self, lock):
        self.ordinal_is_locked = lock
        self.save()


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
