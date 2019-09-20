from django.db import models

from paper.models import Paper
from user.models import User


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
    text = models.TextField()

    class Meta:
        abstract = True


class Thread(BaseComment):
    paper = models.ForeignKey(
        Paper,
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )
    title = models.CharField(max_length=255)

    def __str__(self):
        return '%s: %s' % (self.created_by, self.title)


class Comment(BaseComment):
    parent = models.ForeignKey(
        Thread,
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )


class Reply(BaseComment):
    parent = models.ForeignKey(
        Comment,
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )
