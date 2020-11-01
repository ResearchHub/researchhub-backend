'''
Creates a wallet for users
'''

from django.core.management.base import BaseCommand

from purchase.models import Wallet
from user.models import Author


class Command(BaseCommand):

    def handle(self, *args, **options):
        authors = Author.objects.filter(wallet__isnull=True).iterator()
        for author in authors:
            try:
                has_wallet = author.wallet
            except Exception as e:
                print(e)
                Wallet.objects.create(author=author)
