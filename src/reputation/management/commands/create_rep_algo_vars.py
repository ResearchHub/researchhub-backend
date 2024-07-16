"""
Creates the reputation algorithm variables for a given hub.
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
from reputation.models import AlgorithmVariables


class Command(BaseCommand):
    def handle(self, *args, **options):
        bin_ranges = [1000, 10_000, 100_000, 1_000_000]
        vote = {"value": 1}

        file_path = os.path.join(
            settings.BASE_DIR, "reputation", "misc", "rep_bins.csv"
        )
        with open(file_path, mode="r") as csvfile:
            reader = csv.DictReader(csvfile)
            with transaction.atomic():
                for row in reader:
                    slug = "-".join(row["Subfield"].lower().split("_"))
                    slug_with_index = slug + "-1"
                    try:
                        hub = Hub.objects.get(
                            Q(slug=slug) | Q(slug=slug_with_index), is_used_for_rep=True
                        )
                    except Hub.DoesNotExist:
                        print(f"Hub with slug {slug} not found")
                        continue

                    bin_1 = ast.literal_eval(
                        row["Bin 1 (90-100th %)"]
                    )  # convert string to list ("[4, 0]" -> [4, 0])
                    bin_2 = ast.literal_eval(row["Bin 2 (50-90th %)"])
                    bin_3 = ast.literal_eval(row["Bin 3 (10-50th %)"])
                    bin_4 = ast.literal_eval(row["Bin 4 (0-10th %)"])

                    citations = {
                        "bins": {
                            json.dumps([bin_4[1], bin_4[0]]): round(
                                bin_ranges[0] / bin_4[0]
                            ),
                            json.dumps([bin_4[0], bin_3[0]]): round(
                                (bin_ranges[1] - bin_ranges[0]) / (bin_3[0] - bin_4[0])
                            ),
                            json.dumps([bin_3[0], bin_2[0]]): round(
                                (bin_ranges[2] - bin_ranges[1]) / (bin_2[0] - bin_3[0])
                            ),
                            json.dumps([bin_2[0], bin_1[0]]): round(
                                (bin_ranges[3] - bin_ranges[2]) / (bin_1[0] - bin_2[0])
                            ),
                        },
                    }

                    AlgorithmVariables.objects.create(
                        variables={
                            "citations": citations,
                            "votes": vote,
                            "bins": bin_ranges,
                        },
                        hub_id=hub.id,
                    )
