from django.contrib.postgres.fields import JSONField
from django.db import models


class Webhook(models.Model):
    body = JSONField(blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    from_host = models.CharField(max_length=64, blank=True)
