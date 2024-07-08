"""
Creates the reputation algorithm variables for a given hub.
"""

import csv
import json

from django.core.management.base import BaseCommand
from django.db import transaction

from hub.models import Hub
from reputation.models import AlgorithmVariables


class Command(BaseCommand):
    def handle(self, *args, **options):
        bin_ranges = [1000, 10_000, 100_000, 1_000_000]
        vote = {"value": 1}

        file_path = "../misc/rep_bins.csv"
        with open(file_path, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            with transaction.atomic():
                for row in reader:
                    slug = "-".join(row["Subfield"].lower().split("_"))
                    hub = Hub.objects.get(slug=slug, is_used_for_rep=True)
                    citations = {
                        "bins": {
                            json.dumps([0, row["Bin 4 (0-50th %)"]]): round(
                                bin_ranges[0] / int(row["Bin 4 (0-50th %)"])
                            ),
                            json.dumps(
                                [row["Bin 4 (0-50th %)"], row["Bin 3 (50-70th %)"]]
                            ): round(
                                (bin_ranges[1] - bin_ranges[0])
                                / (
                                    int(row["Bin 3 (50-70th %)"])
                                    - int(row["Bin 4 (0-50th %)"])
                                )
                            ),
                            json.dumps(
                                [row["Bin 3 (50-70th %)"], row["Bin 2 (70-90th %)"]]
                            ): round(
                                (bin_ranges[2] - bin_ranges[1])
                                / (
                                    int(row["Bin 2 (70-90th %)"])
                                    - int(row["Bin 3 (50-70th %)"])
                                )
                            ),
                            json.dumps(
                                [row["Bin 2 (70-90th %)"], row["Bin 1 (90-100th %)"]]
                            ): round(
                                (bin_ranges[3] - bin_ranges[2])
                                / (
                                    int(row["Bin 1 (90-100th %)"])
                                    - int(row["Bin 2 (70-90th %)"])
                                )
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
