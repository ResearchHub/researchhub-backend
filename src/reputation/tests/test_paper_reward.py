import json
import os
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase

from paper.models import Paper
from paper.openalex_util import process_openalex_works
from reputation.related_models.paper_reward import HubCitationValue, PaperReward
from utils.openalex import OpenAlex


class PaperRewardTestCase(TestCase):
    @patch.object(OpenAlex, "get_authors")
    def setUp(self, mock_get_authors):
        works_file_path = os.path.join(
            settings.BASE_DIR, "paper", "tests", "openalex_works.json"
        )
        with open(works_file_path, "r") as file:
            response = json.load(file)
            self.works = response.get("results")

        authors_file_path = os.path.join(
            settings.BASE_DIR, "paper", "tests", "openalex_authors.json"
        )
        with open(authors_file_path, "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(self.works)

            dois = [work.get("doi") for work in self.works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]
            created_papers = Paper.objects.filter(doi__in=dois).order_by("citations")
            self.paper1 = created_papers[0]
            self.paper2 = created_papers[1]

            self.paper1_hub = self.paper1.unified_document.get_primary_hub()
            self.paper2_hub = self.paper2.unified_document.get_primary_hub()

        HubCitationValue.objects.create(
            hub=self.paper1_hub,
            variables={
                "citations": {
                    "bins": {
                        json.dumps((1, 1000000)): json.dumps(
                            {
                                "slope": 0.32872014059165,
                                "intercept": -0.0567277429812658,
                            }
                        )
                    }
                }
            },
        )

    def test_claim_paper_rewards(self):
        paper_reward = PaperReward.claim_paper_rewards(
            self.paper1,
            self.paper1.authors.first(),
            is_open_data=False,
            is_preregistered=False,
        )

        self.assertEqual(paper_reward.citation_change, self.paper1.citations)
        self.assertEqual(paper_reward.citation_count, self.paper1.citations)
        self.assertEqual(paper_reward.rsc_value, (43.77609099046774 / 6.0))
        self.assertFalse(paper_reward.is_open_data)
        self.assertFalse(paper_reward.is_preregistered)

    def test_claim_paper_rewards_open_data(self):
        paper_reward = PaperReward.claim_paper_rewards(
            self.paper1,
            self.paper1.authors.first(),
            is_open_data=True,
            is_preregistered=False,
        )

        self.assertEqual(paper_reward.citation_change, self.paper1.citations)
        self.assertEqual(paper_reward.citation_count, self.paper1.citations)
        self.assertEqual(paper_reward.rsc_value, (43.77609099046774 / 6.0) * 4.0)
        self.assertTrue(paper_reward.is_open_data)
        self.assertFalse(paper_reward.is_preregistered)

    def test_claim_paper_rewards_preregistered(self):
        paper_reward = PaperReward.claim_paper_rewards(
            self.paper1,
            self.paper1.authors.first(),
            False,
            True,
        )

        self.assertEqual(paper_reward.citation_change, self.paper1.citations)
        self.assertEqual(paper_reward.citation_count, self.paper1.citations)
        self.assertEqual(paper_reward.rsc_value, (43.77609099046774 / 6.0) * 3.0)
        self.assertFalse(paper_reward.is_open_data)
        self.assertTrue(paper_reward.is_preregistered)

    def test_claim_paper_rewards_open_data_preregistered(self):
        paper_reward = PaperReward.claim_paper_rewards(
            self.paper1,
            self.paper1.authors.first(),
            True,
            True,
        )

        self.assertEqual(paper_reward.citation_change, self.paper1.citations)
        self.assertEqual(paper_reward.citation_count, self.paper1.citations)
        self.assertEqual(paper_reward.rsc_value, 43.77609099046774)
        self.assertTrue(paper_reward.is_open_data)
        self.assertTrue(paper_reward.is_preregistered)

    def test_distribute_paper_rewards(self):
        paper_reward = PaperReward.claim_paper_rewards(
            self.paper1,
            self.paper1.authors.first(),
            False,
            False,
        )

        paper_reward = PaperReward.distribute_paper_rewards(
            self.paper1,
            self.paper1.authors.first(),
        )

        self.assertIsNotNone(paper_reward.distribution)

    def test_rsc_reward_algo_aerospace_top_bin(self):
        hub_citation_value = HubCitationValue(
            hub=self.paper1_hub,
            variables={
                "citations": {
                    "bins": {
                        json.dumps((1, 100)): json.dumps(
                            {
                                "slope": 0.247331107431,
                                "intercept": -0.522606575151378,
                            }
                        ),
                        json.dumps((101, 1000000)): json.dumps(
                            {
                                "slope": 1.247331107431,
                                "intercept": -0.122606575151378,
                            }
                        ),
                    }
                }
            },
        )

        rsc_reward = hub_citation_value.rsc_reward_algo(1430, True, True)

        self.assertEqual(rsc_reward, 6503.4262371883115)

    def test_rsc_reward_algo_aerospace_first_bin(self):
        hub_citation_value = HubCitationValue(
            hub=self.paper1_hub,
            variables={
                "citations": {
                    "bins": {
                        json.dumps((1, 100)): json.dumps(
                            {
                                "slope": 0.247331107431,
                                "intercept": -0.522606575151378,
                            }
                        ),
                        json.dumps((101, 1000000)): json.dumps(
                            {
                                "slope": 1.247331107431,
                                "intercept": -0.122606575151378,
                            }
                        ),
                    }
                }
            },
        )

        rsc_reward = hub_citation_value.rsc_reward_algo(45, True, True)

        self.assertEqual(rsc_reward, 0.7696341089640361)

    def test_rsc_reward_algo_above_top_bin(self):
        hub_citation_value = HubCitationValue(
            hub=self.paper1_hub,
            variables={
                "citations": {
                    "bins": {
                        json.dumps((1, 100)): json.dumps(
                            {
                                "slope": 0.3,
                                "intercept": -0.056,
                            }
                        ),
                        json.dumps((101, 1000)): json.dumps(
                            {
                                "slope": 0.5,
                                "intercept": 1.23,
                            }
                        ),
                    },
                }
            },
        )

        rsc_reward = hub_citation_value.rsc_reward_algo(10000, True, True)

        self.assertEqual(rsc_reward, 537.0317963702522)
