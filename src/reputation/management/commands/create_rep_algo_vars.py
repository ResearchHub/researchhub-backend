"""
Creates the reputation algorithm variables for a given hub.
"""

import csv
import json
import os

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from hub.models import Hub
from reputation.models import AlgorithmVariables
from researchhub.settings import BASE_DIR


class Command(BaseCommand):
    def handle(self, *args, **options):
        bin_ranges = [1000, 10_000, 100_000, 1_000_000]
        vote = {"value": 1}

        file_path = os.path.join(BASE_DIR, "reputation", "misc", "rep_bins.csv")
        with open(file_path, mode="r") as csvfile:
            reader = csv.DictReader(csvfile)
            with transaction.atomic():
                for row in reader:
                    slug = "-".join(row["Subfield"].lower().split("_"))
                    slug_with_index = slug + "-1"
                    hub = Hub.objects.get(
                        Q(slug=slug) | Q(slug=slug_with_index), is_used_for_rep=True
                    )

                    bin_1 = int(row["Bin 1 (90-100th %)"])
                    bin_2 = int(row["Bin 2 (50-90th %)"])
                    bin_3 = int(row["Bin 3 (10-50th %)"])
                    bin_4 = int(row["Bin 4 (0-10th %)"])

                    citations = {
                        "bins": {
                            json.dumps([0, bin_4]): round(bin_ranges[0] / bin_4),
                            json.dumps(
                                [
                                    bin_4,
                                    bin_3,
                                ]
                            ): round((bin_ranges[1] - bin_ranges[0]) / (bin_3 - bin_4)),
                            json.dumps([bin_3, bin_2]): round(
                                (bin_ranges[2] - bin_ranges[1]) / (bin_2 - bin_3)
                            ),
                            json.dumps([bin_2, bin_1]): round(
                                (bin_ranges[3] - bin_ranges[2]) / (bin_1 - bin_2)
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
