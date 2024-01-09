from django.db import models

from utils.models import DefaultModel

# Fee for "Supporting" Posts/Papers (i.e. Tips)
class SupportFee(DefaultModel):
    expiration_date = models.DateTimeField(null=True)
    rh_pct = models.DecimalField(decimal_places=2, max_digits=5)
    dao_pct = models.DecimalField(decimal_places=2, max_digits=5)
