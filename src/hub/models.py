from django.db import models

from user.models import User


class Hub(models.Model):
    name = models.CharField(max_length=255, unique=True)
    is_locked = models.BooleanField(default=True)
    subscribers = models.ManyToManyField(User, related_name='subscribed_hubs')
