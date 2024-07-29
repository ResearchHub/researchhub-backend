import csv
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
        self.assertTrue(
            HubCitationValue.objects.all().count(), 240
        )  # Should be 244 but csv only has 240 at the moment.
