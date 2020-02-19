from django.db import models
from django.db.models import Q, Count

from paper.models import Vote as PaperVote


class Hub(models.Model):
    UNLOCK_AFTER = 14

    name = models.CharField(max_length=1024, unique=True)
    acronym = models.CharField(max_length=255, default='', blank=True)
    is_locked = models.BooleanField(default=False)
    subscribers = models.ManyToManyField(
        'user.User',
        related_name='subscribed_hubs'
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return '{}, locked: {}'.format(self.name, self.is_locked)

    def save(self, *args, **kwargs):
        self.name = self.name.lower()
        return super(Hub, self).save(*args, **kwargs)

    @property
    def subscriber_count_indexing(self):
        return len(self.subscribers.all())

    def unlock(self):
        self.is_locked = False
        self.save()
