'''
Creates a wallet for users
'''

from django.core.management.base import BaseCommand

from purchase.models import Wallet
from user.models import Author


class Command(BaseCommand):

    def handle(self, *args, **options):
        authors = Author.objects.iterator()
        for author in authors:
            Wallet.objects.create(author=author)
