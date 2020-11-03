import stripe
import json
import hashlib
from datetime import datetime

from django.contrib.postgres.fields import JSONField
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from utils.models import PaidStatusModelMixin


class Wallet(models.Model):
    author = models.OneToOneField(
        'user.Author',
        related_name='wallet',
        on_delete=models.CASCADE,
    )
    eth_address = models.CharField(
        max_length=255,
        null=True
    )
    btc_address = models.CharField(
        max_length=255,
        null=True
    )
    rsc_address = models.CharField(
        max_length=255,
        null=True
    )
    stripe_acc = models.CharField(
        max_length=255,
        null=True
    )
    stripe_verified = models.BooleanField(default=False)


class Support(models.Model):
    STRIPE = 'STRIPE'
    PAYPAL = 'PAYPAL'
    ETH = 'ETH'
    BTC = 'BTC'
    RSC_ON_CHAIN = 'RSC_ON_CHAIN'
    RSC_OFF_CHAIN = 'RSC_OFF_CHAIN'

    SINGLE = 'SINGLE'
    MONTHLY = 'MONTHLY'

    payment_type_choices = [
        (STRIPE, STRIPE),
        (PAYPAL, PAYPAL),
        (ETH, ETH),
        (BTC, BTC),
        (RSC_ON_CHAIN, RSC_ON_CHAIN),
        (RSC_OFF_CHAIN, RSC_OFF_CHAIN),
    ]

    duration_choices = [
        (SINGLE, SINGLE),
        (MONTHLY, MONTHLY)
    ]

    sender = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='supported_works'
    )
    recipient = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='supported_by'
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
    payment_type = models.CharField(
        choices=payment_type_choices,
        max_length=16
    )
    duration = models.CharField(
        choices=duration_choices,
        max_length=8
    )
    amount = models.CharField(
        max_length=255
    )
    proof = JSONField(null=True)


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
    group = models.ForeignKey(
        AggregatePurchase,
        null=True,
        on_delete=models.SET_NULL,
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
        day_multiplier = 60 * 60 * 24
        previous_boost_time = 0
        if self.item.purchases:
            previous_boosts = self.item.purchases.exclude(id=self.id)
            if previous_boosts.exists():
                previous_boost_amounts = previous_boosts.values_list(
                    'amount',
                    flat=True
                )
                previous_boost_time += sum(map(float, previous_boost_amounts))

        if amount:
            boost_time = float(amount) + previous_boost_time
            boost_time = boost_time * day_multiplier
            return boost_time

        timestamp = self.created_date.timestamp()
        boost_amount = float(self.amount) + previous_boost_time
        boost_time = timestamp + (boost_amount * day_multiplier)
        current_timestamp = datetime.utcnow().timestamp()

        if boost_time > current_timestamp:
            new_boost_time = boost_time - current_timestamp
            return new_boost_time
        return 0

    def get_aggregate_group(self):
        user = self.user
        object_id = self.object_id
        content_type = self.content_type
        paid_status = self.paid_status

        aggregate_group = None
        aggregates = AggregatePurchase.objects.filter(
            user=user,
            content_type=content_type,
            object_id=object_id,
            paid_status=paid_status,
            purchases__boost_time__gt=0
        ).distinct()

        if aggregates.exists():
            aggregate_group = aggregates.last()
        else:
            aggregate_group = AggregatePurchase.objects.create(
                user=user,
                content_type=content_type,
                object_id=object_id,
                paid_status=paid_status
            )
        return aggregate_group


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

    # TODO: why is this a char field?
    amount = models.CharField(max_length=255)
    testnet_amount = models.CharField(max_length=255, default=0, null=True, blank=True)

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
