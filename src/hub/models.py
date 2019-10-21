from django.db import models


class Hub(models.Model):
    name = models.CharField(max_length=255, unique=True)
    is_locked = models.BooleanField(default=True)
