from django.db import models
from django.contrib.postgres.fields import JSONField

from user.models import User
from paper.models import Paper

class Summary(models.Model):
    summary = JSONField(default=None, null=True)
    paper = models.ForeignKey(Paper, related_name='summary', on_delete='CASCADE')
    user = models.ForeignKey(User, related_name='edits', on_delete='CASCADE')
    current = models.BooleanField(default=False, null=False, blank=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        return self.id