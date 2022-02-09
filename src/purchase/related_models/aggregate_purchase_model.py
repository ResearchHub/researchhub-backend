from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from utils.models import PaidStatusModelMixin


class AggregatePurchase(PaidStatusModelMixin):
    user = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='aggregate_purchases'
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey(
        'content_type',
        'object_id'
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
