from django.db import models


class Wallet(models.Model):
    author = models.OneToOneField(
        "user.Author",
        related_name="wallet",
        on_delete=models.CASCADE,
    )
    eth_address = models.CharField(max_length=255, null=True)
    btc_address = models.CharField(max_length=255, null=True)
    rsc_address = models.CharField(max_length=255, null=True)
