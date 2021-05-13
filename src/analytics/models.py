from django.contrib.postgres.fields import JSONField
from django.db import models

from researchhub.lib import CREATED_LOCATION_CHOICES
from user.models import User

INTERACTIONS = {
    'CLICK': 'CLICK',
    'VIEW': 'VIEW',
}

INTERACTION_CHOICES = [
    (INTERACTIONS['CLICK'], INTERACTIONS['CLICK']),
    (INTERACTIONS['VIEW'], INTERACTIONS['VIEW']),
]


class WebsiteVisits(models.Model):
    uuid = models.CharField(max_length=36)
    saw_signup_banner = models.BooleanField(default=False)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.uuid}'


class PaperEvent(models.Model):
    CLICK = 'CLICK'
    VIEW = 'VIEW'
    PAPER = 'PAPER'

    paper = models.ForeignKey(
        'paper.Paper',
        on_delete=models.SET_NULL,
        related_name='events',
        related_query_name='event',
        null=True
    )
    user = models.ForeignKey(
        'user.User',
        on_delete=models.SET_NULL,
        related_name='paper_events',
        related_query_name='paper_event',
        null=True,
        blank=True
    )
    interaction = models.CharField(
        choices=INTERACTION_CHOICES,
        max_length=255,
        default=None,
        null=True,
        blank=True
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    created_location = models.CharField(
        choices=CREATED_LOCATION_CHOICES,
        max_length=255,
        default=None,
        null=True,
        blank=True
    )
    created_location_meta = JSONField(blank=True, null=True)
    paper_is_boosted = models.BooleanField()
