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
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
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
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['content_type', 'object_id'],
                name='unique_endorsement'
            )
        ]


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
    votes = GenericRelation(Vote)
    flags = GenericRelation(Flag)
    endorsement = GenericRelation(Endorsement)
    plain_text = models.TextField(default='', blank=True)

    class Meta:
        abstract = True

    @property
    def created_by_author_profile_indexing(self):
        if self.created_by:
            author = self.created_by.author_profile
            if author:
                return author
        return None

    @property
    def score_indexing(self):
        return self.calculate_score()

    def calculate_score(self):
        upvotes = self.votes.filter(vote_type=Vote.UPVOTE)
        downvotes = self.votes.filter(vote_type=Vote.DOWNVOTE)
        score = len(upvotes) - len(downvotes)
        return score


class Thread(BaseComment):
    title = models.CharField(max_length=255)
    paper = models.ForeignKey(
        Paper,
        on_delete=models.SET_NULL,
        related_name='threads',
        blank=True,
        null=True
    )

    def __str__(self):
        return '%s: %s' % (self.created_by, self.title)

    @property
    def comment_count_indexing(self):
        return len(self.comments.all())

    @property
    def paper_indexing(self):
        if self.paper is not None:
            return self.paper.id

    @property
    def paper_title_indexing(self):
        if self.paper is not None:
            return self.paper.title


class Reply(BaseComment):
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )
    object_id = models.PositiveIntegerField()
    parent = GenericForeignKey('content_type', 'object_id')

    @property
    def paper(self):
        comment = self.get_comment_of_reply()
        thread = comment.parent
        paper = thread.parent
        return paper

    def get_comment_of_reply(self):
        obj = self
        while isinstance(obj, Reply):
            obj = obj.parent

        if isinstance(obj, Comment):
            return obj
        return None


class Comment(BaseComment):
    parent = models.ForeignKey(
        Thread,
        on_delete=models.SET_NULL,
        related_name='comments',
        blank=True,
        null=True
    )
    replies = GenericRelation(Reply)

    def __str__(self):
        return '{} - {}'.format(self.created_by, self.plain_text)

    @property
    def paper(self):
        thread = self.parent
        paper = thread.parent
        return paper
