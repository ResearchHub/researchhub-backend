from django.db import models

from utils.models import DefaultModel


class RscPurchaseFee(DefaultModel):
    """
    Fee for RSC purchases (i.e. via payment intents)
    """
    expiration_date = models.DateTimeField(null=True)
    rh_pct = models.DecimalField(decimal_places=2, max_digits=5)
    dao_pct = models.DecimalField(decimal_places=2, max_digits=5)
