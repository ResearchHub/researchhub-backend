import json

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
# Create your models here.


class Purchase(models.Model):
    OFF_CHAIN = 'OFF_CHAIN'
    ON_CHAIN = 'ON_CHAIN'

    INITIATED = 'INITIATED'
    PENDING = 'PENDING'
    SUCCESS = 'SUCCESS'

    PURCHASE_TYPE_CHOICES = [
        (OFF_CHAIN, OFF_CHAIN),
        (ON_CHAIN, ON_CHAIN),
    ]

    STATUS_CHOICES = [
        (INITIATED, INITIATED),
        (PENDING, PENDING),
        (SUCCESS, SUCCESS)
    ]

    user = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='purchases'
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey('content_type', 'object_id')

    purchase_type = models.CharField(
        choices=PURCHASE_TYPE_CHOICES,
        default=ON_CHAIN,
        max_length=16,
    )
    status = models.CharField(
        choices=STATUS_CHOICES,
        default=INITIATED,
        max_length=16,
    )
    transaction_id = models.CharField(
        max_length=64,
        blank=True,
        null=True
    )
    amount = models.FloatField()

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __hash__(self):
        return hash(self.get_serialized_representation())

    def hash(self):
        data = self.get_serialized_representation()
        data_hash = hash(data)
        return {'data': data, 'hash': data_hash}

    def get_serialized_representation(self):
        data = json.dumps({
            'id': self.id,
            'content_type': self.content_type.id,
            'object_id': self.object_id,
            'purchase_type': self.purchase_type,
            'status': self.status,
            'transaction_id': self.transaction_id,
            'amount': self.amount,
            'created_date': hash(self.created_date),
            'updated_date': hash(self.updated_date)
        })
        return data
