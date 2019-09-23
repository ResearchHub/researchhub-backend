from django.db import models
from user import User
from paper import Paper
class Summary(models.Model):
    summary = JSONField(default=None, null=True)
    paper = ForeignKey(Paper, related_name='summary')

    def __str__(self):
        return self.id

class Edits(models.Model):
    edits = JSONField(default=None, null=True)
    user = models.ForeignKey(
        User,
        related_name='edits',
    )

    def __str__(self):
        return self.id
