'''
Creates a wallet for users
'''

import datetime

from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from reputation.models import DistributionAmount, Contribution
from reputation.tasks import create_contribution, reward_calculation
from user.models import Action


class Command(BaseCommand):

    def handle(self, *args, **options):
        reward_calculation(False)
