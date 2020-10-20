'''
Creates a wallet for users
'''

from django.core.management.base import BaseCommand

from purchase.models import Wallet
from user.models import User


class Command(BaseCommand):

    def handle(self, *args, **options):
        users = User.objects.iterator()
        for user in users:
            Wallet.objects.create(user=user)
