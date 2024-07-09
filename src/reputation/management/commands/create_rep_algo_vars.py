"""
Creates the reputation algorithm variables for a given hub.
"""

import csv
import json

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from hub.models import Hub
from reputation.models import AlgorithmVariables


class Command(BaseCommand):
    def handle(self, *args, **options):
        bin_ranges = [1000, 10_000, 100_000, 1_000_000]
        vote = {"value": 1}

        file_path = "../misc/rep_bins.csv"
        with open(file_path, mode="r") as csvfile:
            reader = csv.DictReader(csvfile)
            with transaction.atomic():
                for row in reader:
                    print(row)
                    slug = "-".join(row["Subfield"].lower().split("_"))
                    slug_with_index = slug + "-1"
                    hub = Hub.objects.get(
                        Q(slug=slug) | Q(slug=slug_with_index), is_used_for_rep=True
                    )
                    citations = {
                        "bins": {
                            json.dumps([0, row["Bin 4 (0-10th %)"]]): round(
                                bin_ranges[0] / int(row["Bin 4 (0-10th %)"])
                            ),
                            json.dumps(
                                [row["Bin 4 (0-10th %)"], row["Bin 3 (10-50th %)"]]
                            ): round(
                                (bin_ranges[1] - bin_ranges[0])
                                / (
                                    int(row["Bin 3 (10-50th %)"])
                                    - int(row["Bin 4 (0-10th %)"])
                                )
                            ),
                            json.dumps(
                                [row["Bin 3 (10-50th %)"], row["Bin 2 (50-90th %)"]]
                            ): round(
                                (bin_ranges[2] - bin_ranges[1])
                                / (
                                    int(row["Bin 2 (50-90th %)"])
                                    - int(row["Bin 3 (10-50th %)"])
                                )
                            ),
                            json.dumps(
                                [row["Bin 2 (50-90th %)"], row["Bin 1 (90-100th %)"]]
                            ): round(
                                (bin_ranges[3] - bin_ranges[2])
                                / (
                                    int(row["Bin 1 (90-100th %)"])
                                    - int(row["Bin 2 (50-90th %)"])
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
