"""
Creates a wallet for users
"""

import datetime

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from reputation.models import Contribution, DistributionAmount
from reputation.tasks import create_contribution, new_reward_calculation
from user.models.action import Action


class Command(BaseCommand):
    def handle(self, *args, **options):
        new_reward_calculation(False)
