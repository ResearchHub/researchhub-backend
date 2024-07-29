import csv
import json
import os

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from hub.models import Hub
from reputation.models import HubCitationValue


class CreateRewardAlgoVarsTestCase(TestCase):
    def setUp(self):
        file_path = os.path.join(
            settings.BASE_DIR, "reputation", "misc", "reward_algo.csv"
        )
        self.hubs = []
        with open(file_path, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                slug = "-".join(row["Subfield"].lower().split("_"))
                self.hubs.append(
                    Hub.objects.create(slug=slug, name=slug, is_used_for_rep=True)
                )

    def test_create_reward_algo_vars(self):
        # Call the management command
        call_command("create_reward_algo_vars")
        # Assert that the reward algorithm variables are created for the hub
        self.assertEqual(HubCitationValue.objects.all().count(), 244)

    def test_aerospace_rewar_algo_vars(self):
        # Call the management command
        call_command("create_reward_algo_vars")
        hub = Hub.objects.get(slug="aerospace-engineering")
        algo_var = HubCitationValue.objects.get(hub=hub)

        self.assertDictEqual(
            algo_var.variables["citations"]["bins"],
            {
                json.dumps((1, 3)): json.dumps(
                    {
                        "slope": 0.26361953555166395,
                        "intercept": 0.38240072911003764,
                    }
                ),
                json.dumps((4, 10)): json.dumps(
                    {
                        "slope": 0.5312640019045695,
                        "intercept": 0.24898386052475074,
                    }
                ),
                json.dumps((11, 26)): json.dumps(
                    {
                        "slope": 0.9368936426887948,
                        "intercept": -0.1489352697586166,
                    }
                ),
                json.dumps((27, 60)): json.dumps(
                    {
                        "slope": 1.3436077598045197,
                        "intercept": -0.708836932048057,
                    }
                ),
                json.dumps((61, 160)): json.dumps(
                    {
                        "slope": 1.6530749281588402,
                        "intercept": -1.2517839350382407,
                    }
                ),
                json.dumps((161, 359)): json.dumps(
                    {
                        "slope": 1.8666873929853267,
                        "intercept": -1.7541341132399557,
                    }
                ),
                json.dumps((360, 494)): json.dumps(
                    {
                        "slope": 1.050832052541524,
                        "intercept": 0.4043890994381161,
                    }
                ),
                json.dumps((495, 1430)): json.dumps(
                    {
                        "slope": 1.247331107431001,
                        "intercept": -0.12260657515137785,
                    }
                ),
            },
        )
