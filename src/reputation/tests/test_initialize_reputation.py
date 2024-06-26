import json
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from hub.models import Hub
from paper.models import Paper
from paper.tests.helpers import create_paper
from reputation.models import AlgorithmVariables, Score, ScoreChange
from researchhub_case.constants.case_constants import APPROVED
from researchhub_case.models import AuthorClaimCase
from researchhub_case.tasks import after_approval_flow
from user.models import Author, User


class InitializeReputationCommandTestCase(TestCase):
    def setUp(self):
        # Create test data for paper_paper table
        paper1 = create_paper(title="Paper 1")
        paper1.citations = 100
        paper1.save()
        paper2 = create_paper(title="Paper 2")
        paper2.citations = 32
        paper2.save()

        # Create test data for hubs table
        self.hub1 = Hub.objects.create(name="Hub 1", is_used_for_rep=True)
        self.hub2 = Hub.objects.create(name="Hub 2", is_used_for_rep=True)
        self.hub3 = Hub.objects.create(name="Hub 3", is_used_for_rep=False)

        # Add hubs to papers
        paper1.hubs.add(self.hub1)
        paper2.hubs.add(self.hub2)
        paper2.hubs.add(self.hub3)

        # Add user, an author is automatically created for this user.
        self.user = User.objects.create_user(username="user1", password="pass1")

        # Add author claim
        self.attribute_paper_to_author(self.user, paper1)
        self.attribute_paper_to_author(self.user, paper2)

        self.citation_count = 10  # TODO remove?
        self.bins = (
            [
                [0, 1000],
                [1000, 10000],
                [10000, 100000],
                [100000, 100000],
            ],
        )

        self.citation_bins = {
            json.dumps((0, 2)): 50,
            json.dumps((2, 12)): 100,
            json.dumps((12, 200)): 250,
            json.dumps((200, 2800)): 100,
        }

        # Create test data for algorithm_variables table
        algorithm_variables1 = AlgorithmVariables.objects.create(
            variables={
                "citations": {
                    "bins": self.citation_bins,
                },
                "votes": {"value": 1},
                "bins": self.citation_bins,
            },
            hub=self.hub1,
        )

        algorithm_variables2 = AlgorithmVariables.objects.create(
            variables={
                "citations": {
                    "bins": self.citation_bins,
                },
                "votes": {"value": 1},
                "bins": self.citation_bins,
            },
            hub=self.hub2,
        )

    def test_initialize_reputation_command(self):
        call_command("initialize_reputation", self.user.id)

        # Check if the score is created
        self.assertEqual(Score.objects.count(), 2)

        # Check if the score change is created
        self.assertEqual(ScoreChange.objects.count(), 2)

        # Check if the score is created with the correct score
        score1 = Score.objects.get(hub=self.hub1, author=self.user.author_profile)
        self.assertEqual(score1.score, 23100)

        # Check if the score change is created with the correct score change
        score_change1 = ScoreChange.objects.get(score=score1)
        self.assertEqual(score_change1.score_change, 23100)

        # Check if the score is created with the correct score
        score2 = Score.objects.get(hub=self.hub2, author=self.user.author_profile)
        self.assertEqual(score2.score, 6100)

        # Check if the score change is created with the correct score change
        score_change2 = ScoreChange.objects.get(score=score2)
        self.assertEqual(score_change2.score_change, 6100)

    def attribute_paper_to_author(self, user, paper):
        case = AuthorClaimCase.objects.create(
            target_paper=paper, requestor=user, status=APPROVED
        )

        after_approval_flow(case.id)
        user.refresh_from_db()
        paper.refresh_from_db()
