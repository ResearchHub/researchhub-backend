from django.db import models

from user.models import User


class Hub(models.Model):
    name = models.CharField(max_length=1024, unique=True)
    is_locked = models.BooleanField(default=True)
    subscribers = models.ManyToManyField(User, related_name='subscribed_hubs')
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
