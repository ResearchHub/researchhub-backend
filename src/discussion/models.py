from django.contrib.contenttypes.fields import (
    GenericForeignKey,
    GenericRelation
)
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import JSONField
from django.db import models

from paper.models import Paper
from user.models import User

HELP_TEXT_WAS_EDITED = (
    'True if the comment text was edited after first being created.'
)
HELP_TEXT_IS_PUBLIC = (
    'Hides the comment from the public.'
)
HELP_TEXT_IS_REMOVED = (
    'Hides the comment because it is not allowed.'
)


class BaseComment(models.Model):
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
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

    class Meta:
        abstract = True


class Thread(BaseComment):
    paper = models.ForeignKey(
        Paper,
        on_delete=models.SET_NULL,
        related_name='threads',
        blank=True,
        null=True
    )
    title = models.CharField(max_length=255)

    def __str__(self):
        return '%s: %s' % (self.created_by, self.title)


class Reply(BaseComment):
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )
    object_id = models.PositiveIntegerField()
    parent = GenericForeignKey('content_type', 'object_id')


class Comment(BaseComment):
    parent = models.ForeignKey(
        Thread,
        on_delete=models.SET_NULL,
        related_name='comments',
        blank=True,
        null=True
    )
    replies = GenericRelation(Reply)


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
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_date = models.DateTimeField(auto_now_add=True)
    vote_type = models.IntegerField(choices=VOTE_TYPE_CHOICES)


class Flag(models.Model):
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey('content_type', 'object_id')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_date = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=255, blank=True)
