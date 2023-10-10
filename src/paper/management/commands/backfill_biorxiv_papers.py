"""
Adding preprints from biorxiv
"""

import requests
from django.core.management.base import BaseCommand
from django.db.models import Q

from paper.tasks import pull_biorxiv_papers


class Command(BaseCommand):
    def handle(self, *args, **options):
        pull_biorxiv_papers()
