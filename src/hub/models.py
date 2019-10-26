from django.db import models

from user.models import User


class Hub(models.Model):
    name = models.CharField(max_length=1024, unique=True)
    is_locked = models.BooleanField(default=True)
    subscribers = models.ManyToManyField(User, related_name='subscribed_hubs')

    def __str__(self):
        return '{}, locked: {}'.format(self.name, self.is_locked)

    def save(self, *args, **kwargs):
        self.name = self.name.lower()
        return super(Hub, self).save(*args, **kwargs)
