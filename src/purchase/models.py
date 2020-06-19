import json
import hashlib
from datetime import datetime

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from utils.models import PaidStatusModelMixin


class Purchase(PaidStatusModelMixin):
    OFF_CHAIN = 'OFF_CHAIN'
    ON_CHAIN = 'ON_CHAIN'

    BOOST = 'BOOST'

    PURCHASE_METHOD_CHOICES = [
        (OFF_CHAIN, OFF_CHAIN),
        (ON_CHAIN, ON_CHAIN),
    ]

    PURCHASE_TYPE_CHOICES = [
        (BOOST, BOOST)
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
    item = GenericForeignKey(
        'content_type',
        'object_id'
    )

    purchase_method = models.CharField(
        choices=PURCHASE_METHOD_CHOICES,
        max_length=16,
    )
    purchase_type = models.CharField(
        choices=PURCHASE_TYPE_CHOICES,
        max_length=16
    )

    transaction_hash = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    purchase_hash = models.CharField(
        max_length=32,
        blank=True,
        null=True
    )
    amount = models.CharField(max_length=255)
    boost_time = models.FloatField(null=True)

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def hash(self):
        md5 = hashlib.md5(self.get_serialized_representation().encode())
        hexdigest = md5.hexdigest()
        return hexdigest

    def data(self):
        data = self.get_serialized_representation()
        data_hash = hash(data)
        return {'data': data, 'hash': data_hash}

    def get_serialized_representation(self):
        data = json.dumps({
            'id': self.id,
            'content_type': self.content_type.id,
            'object_id': self.object_id,
            'purchase_method': self.purchase_method,
            'purchase_type': self.purchase_type,
            'paid_status': self.paid_status,
            'transaction_hash': self.transaction_hash,
            'amount': self.amount,
            'created_date': self.created_date.isoformat(),
            'updated_date': self.updated_date.isoformat()
        })
        return data

    def get_boost_time(self, amount=None):
        if amount:
            amount = float(amount)
            boost_time = amount * 60
            return boost_time

        timestamp = self.created_date.timestamp()
        boost_amount = float(self.amount)
        boost_time = timestamp + (boost_amount * 60 * 60)
        current_timestamp = datetime.utcnow().timestamp()

        if boost_time > current_timestamp:
            new_boost_time = (
                ((boost_time - current_timestamp) / 60)
            )
            return new_boost_time

        return 0


class Balance(models.Model):
    user = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='balances'
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    object_id = models.PositiveIntegerField(null=True)
    source = GenericForeignKey('content_type', 'object_id')

    amount = models.CharField(max_length=255)

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
