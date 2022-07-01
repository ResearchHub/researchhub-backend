from django.db import models


class DistributionAmount(models.Model):
    created_date = models.DateTimeField(auto_now_add=True)
    distributed_date = models.DateTimeField(auto_now=True)
    amount = models.IntegerField(default=1000000)
    distributed = models.BooleanField(default=False)
