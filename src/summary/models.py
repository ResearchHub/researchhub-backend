from django.db import models
from django.contrib.postgres.fields import JSONField

from user.models import User

class Summary(models.Model):
    summary = JSONField(default=None, null=True)
    user = models.ForeignKey(User, related_name='edits', on_delete='CASCADE')
    previous = models.ForeignKey("self", default=None, null=True, blank=True, related_name='next', on_delete='CASCADE')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        return f'{self.id}'