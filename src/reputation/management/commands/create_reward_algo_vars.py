"""
Creates the reward algorithm variables for a given hub.
"""

import ast
import csv
import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from hub.models import Hub
from reputation.models import HubCitationValue


class Command(BaseCommand):
    def handle(self, *args, **options):
        file_path = os.path.join(
            settings.BASE_DIR, "reputation", "misc", "reward_algo.csv"
        )
        with open(file_path, mode="r") as csvfile:
            reader = csv.DictReader(csvfile)
            with transaction.atomic():
                for row in reader:
                    slug = "-".join(row["Subfield"].lower().split("_"))
                    slug_with_index = slug + "-1"
                    hub = Hub.objects.get(
                        Q(slug=slug) | Q(slug=slug_with_index), is_used_for_rep=True
                    )

                    citations = {}
                    bins = {}
                    for v in range(1, 9):
                        bin = ast.literal_eval(row[f"Bin_{v}"])
                        lower_bound = bin[0] + 1
                        if v == 1:
                            lower_bound = (
                                1  # first bin starts at 1 so should not be incremented.
                            )
                        upper_bound = bin[1]

                        slope = ast.literal_eval(row[f"Slope_{v}"])
                        intercept = ast.literal_eval(row[f"Intercept_{v}"])

                        bins[json.dumps([lower_bound, upper_bound])] = json.dumps(
                            {"slope": slope, "intercept": intercept}
                        )

                    citations["bins"] = bins

                    HubCitationValue.objects.create(
                        variables={
                            "citations": citations,
                        },
                        hub=hub,
                    )
