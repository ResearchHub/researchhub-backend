"""
Update the reputation algorithm for a given hub.
"""

from django.core.management.base import BaseCommand
from django.db.models import Sum

from reputation.models import AlgorithmVariables, Score, ScoreChange
from user.models import Author


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "hub_id",
            type=int,
            help="ID of the hub for which to update reputation algorithm",
        )

        parser.add_argument(
            "variables",
            type=dict,
            help="New variables for the reputation algorithm",
        )

    def handle(self, *args, **options):
        hub_id = options["hub_id"]
        variables = options["variables"]
        algorithm_vars = AlgorithmVariables(
            variables=variables,
            hub_id=hub_id,
        )
        algorithm_vars.save()
        # TODO recalculate reputation scores for all authors in the hub
