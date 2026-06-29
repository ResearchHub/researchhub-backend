import math

from django.db import models
from django.db.models import JSONField

OPEN_ACCESS_MULTIPLIER = 1.0
OPEN_DATA_MULTIPLIER = 3.0
PREREGISTERED_MULTIPLIER = 2.0
REWARD_MULTIPLIER = 5.0


class HubCitationValue(models.Model):
    hub = models.ForeignKey("hub.Hub", on_delete=models.CASCADE, db_index=True)
    # {"citations":
    #   {"bins":{
    #       (0, 2): {"slope": 0.29, "intercept": 10},
    #       (2, 12): {"slope": 0.35, "intercept": 100},
    #       (12, 200): {"slope": 0.40, "intercept": 200},
    #       (200, 2800): {"slope": 0.53, "intercept": 300}
    #   }},
    # }
    variables = JSONField(null=True, blank=True, default=None)

    created_date = models.DateTimeField(auto_now_add=True)


class PaperReward(models.Model):
    paper = models.ForeignKey("paper.Paper", on_delete=models.CASCADE, db_index=True)
    author = models.ForeignKey("user.Author", on_delete=models.CASCADE, db_index=True)
    citation_change = models.PositiveIntegerField()
    citation_count = models.PositiveIntegerField()
    rsc_value = models.FloatField()
    is_open_data = models.BooleanField(default=False)
    is_preregistered = models.BooleanField(default=False)
    distribution = models.ForeignKey(
        "reputation.Distribution",
        on_delete=models.CASCADE,
        db_index=True,
        default=None,
        null=True,
        blank=True,
    )
    hub_citation_value = models.ForeignKey(
        "reputation.HubCitationValue",
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
    )

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
