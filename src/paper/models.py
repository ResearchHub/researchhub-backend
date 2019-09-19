from django.db import models
from user.models import UserProfile


class Paper(models.Model):
    title = models.CharField(max_length=255)
    authors = models.ManyToManyField(
        UserProfile,
        related_name='authored_papers',
        blank=True
    )

    def __str__(self):
        authors = list(self.authors.all())
        return '%s: %s' % (self.title, authors)
