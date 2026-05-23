from django.core.management.base import BaseCommand

from hub.tasks import calculate_and_set_hub_counts


class Command(BaseCommand):
    help = (
        "Calculate and set hub counts for all hubs. e.g. discussion count, paper count"
    )

    def handle(self, *args, **kwargs):
        calculate_and_set_hub_counts()
