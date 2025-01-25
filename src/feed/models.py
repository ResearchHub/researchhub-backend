from django.contrib.contenttypes.models import ContentType
from django.db import models


class FeedEntry(models.Model):
    content_type = models.CharField(max_length=255)
    content_object = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    created_date = models.DateTimeField(auto_now_add=True)
