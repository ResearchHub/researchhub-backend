from datetime import datetime

from django.core.management.base import BaseCommand

from hub.models import Hub
from hub.tasks import calculate_and_set_hub_counts
from paper.related_models.paper_model import Paper
from tag.models import Concept
from utils.openalex import OpenAlex


class Command(BaseCommand):
    help = (
        "Calculate and set hub counts for all hubs. e.g. discussion count, paper count"
    )

    def handle(self, *args, **kwargs):
        calculate_and_set_hub_counts()
