"""
Calculate rep for a given author.
"""

from django.core.management.base import BaseCommand

from user.models import User


class Command(BaseCommand):
    def handle(self, *args, **options):
        for user in User.objects.iterator():
            try:
                user.calculate_hub_scores()
            except Exception as e:
                print(f"Error calculating rep for user {user.id}: {e}")
                continue
