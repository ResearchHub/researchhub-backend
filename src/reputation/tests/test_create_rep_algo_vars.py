import csv

from django.core.management import call_command
from django.test import TestCase

from hub.models import Hub
from reputation.models import AlgorithmVariables


class CreateRepAlgoVarsTest(TestCase):
    def test_create_rep_algo_vars(self):
        file_path = "../misc/rep_bins.csv"
        with open(file_path, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                slug = "-".join(row["Subfield"].lower().split("_"))
                Hub.objects.create(slug=slug, name=slug, is_used_for_rep=True)

        call_command("create_rep_algo_vars")

        algo_vars = AlgorithmVariables.objects.all()
        self.assertEqual(algo_vars.count(), 244)

        hub = Hub.objects.get(slug="artificial-intelligence")
        algo_var = AlgorithmVariables.objects.get(hub=hub)

        self.assertEqual(
            algo_var.variables["citations"]["bins"],
            {
                '[0, "1"]': 1000,
                '["1", "7"]': 1500,
                '["7", "21"]': 6429,
                '["21", "113"]': 9783,
            },
        )
