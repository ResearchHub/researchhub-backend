from django.db import models
from user import User

class Summary(models.Model):
    summary = JSONField(default=None, null=True)

    def __str__(self):
        return self.id

class Edits(models.Model):
    edits = JSONField(default=None, null=True)
    user = models.ForeignKey(
        User,
        related_name='edits',
    )
