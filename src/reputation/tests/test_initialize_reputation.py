import json
from unittest.mock import PropertyMock, patch

from django.core.exceptions import ObjectDoesNotExist
from django.core.management import call_command
from django.test import TestCase

from discussion.reaction_models import Vote
from discussion.tests.helpers import create_rh_comment, create_vote
from hub.models import Hub
from paper.tests.helpers import create_paper
from reputation.models import AlgorithmVariables, Score, ScoreChange
from researchhub_case.constants.case_constants import APPROVED
from researchhub_case.models import AuthorClaimCase
from researchhub_case.tasks import after_approval_flow
from user.models import User


class InitializeReputationCommandTestCase(TestCase):
    def setUp(self):
        # Create test data for paper_paper table
        paper1 = create_paper(title="Paper 1")
        paper1.citations = 100
        paper1.save()
        paper2 = create_paper(title="Paper 2")
        paper2.citations = 32
        paper2.save()
        paper2.citations = 64
        paper2.save()
        paper3 = create_paper(title="Paper 3")
        paper3.citations = 10
        paper3.save()

        # Create test data for hubs table
        self.hub1 = Hub.objects.create(name="Hub 1", is_used_for_rep=True)
        self.hub2 = Hub.objects.create(name="Hub 2", is_used_for_rep=True)
        self.hub3 = Hub.objects.create(name="Hub 3", is_used_for_rep=False)

        # Add hubs to papers
        paper1.hubs.add(self.hub1)
        paper2.hubs.add(self.hub2)
        paper2.hubs.add(self.hub3)
        paper3.hubs.add(self.hub2)

        # Add user, an author is automatically created for this user.
        self.user_author = User.objects.create_user(username="user1", password="pass1")
        self.user_basic = User.objects.create_user(username="user2", password="pass2")
        self.user_no_author = User.objects.create_user(
            username="user3", password="pass3"
        )

        bins = (
            [
                [0, 1000],
                [1000, 10000],
                [10000, 100000],
                [100000, 100000],
            ],
        )

        old_vitation_bins = {
            json.dumps((0, 2)): 5,
            json.dumps((2, 12)): 10,
            json.dumps((12, 200)): 25,
            json.dumps((200, 2800)): 10,
        }

        citation_bins = {
            json.dumps((0, 2)): 50,
            json.dumps((2, 12)): 100,
            json.dumps((12, 200)): 250,
            json.dumps((200, 2800)): 100,
        }

        # Create an old unused algorithm_variables row
        AlgorithmVariables.objects.create(
            variables={
                "citations": {
                    "bins": old_vitation_bins,
                },
                "votes": {"value": 1},
                "bins": bins,
            },
            hub=self.hub1,
        )

        # Create test data for algorithm_variables table
        AlgorithmVariables.objects.create(
            variables={
                "citations": {
                    "bins": citation_bins,
                },
                "votes": {"value": 1},
                "bins": bins,
            },
            hub=self.hub1,
        )

        # Create an old unused algorithm_variables row
        AlgorithmVariables.objects.create(
            variables={
                "citations": {
                    "bins": old_vitation_bins,
                },
                "votes": {"value": 1},
                "bins": bins,
            },
            hub=self.hub2,
        )

        # Create test data for algorithm_variables table
        AlgorithmVariables.objects.create(
            variables={
                "citations": {
                    "bins": citation_bins,
                },
                "votes": {"value": 1},
                "bins": bins,
            },
            hub=self.hub2,
        )

        # Create comments
        comment1 = create_rh_comment(paper=paper1, created_by=self.user_author)
        comment2 = create_rh_comment(paper=paper1, created_by=self.user_author)

        # Upvote comment 1
        create_vote(self.user_author, comment1, Vote.UPVOTE)
        create_vote(self.user_basic, comment1, Vote.UPVOTE)

        # Downvote comment 2
        create_vote(self.user_author, comment2, Vote.UPVOTE)

        # Upvote paper 1
        create_vote(self.user_author, paper1, Vote.UPVOTE)

        # Add author claim
        self.attribute_paper_to_author(self.user_author, paper1)
        self.attribute_paper_to_author(self.user_author, paper2)
        self.attribute_paper_to_author(self.user_author, paper3)

    def test_initialize_reputation_command(self):
        call_command("initialize_reputation")

        # Check if the score is created
        self.assertEqual(Score.objects.count(), 2)

        # Check if the score change is created
        self.assertEqual(ScoreChange.objects.count(), 8)

        # Check if the score is created with the correct score
        score1 = Score.objects.get(
            hub=self.hub1, author=self.user_author.author_profile
        )

        self.assertEqual(score1.score, 23104)

        # Check if the score change is created with the correct score change
        score_changes1 = ScoreChange.objects.filter(score=score1)
        self.assertEqual(score_changes1[0].score_change, 23100)
        self.assertEqual(score_changes1[1].score_change, 1)
        self.assertEqual(score_changes1[2].score_change, 1)
        self.assertEqual(score_changes1[3].score_change, 1)
        self.assertEqual(score_changes1[4].score_change, 1)

        # Check if the score is created with the correct score
        score2 = Score.objects.get(
            hub=self.hub2, author=self.user_author.author_profile
        )
        # 2*50 + 10*100 + 52*250 = 14100
        self.assertEqual(score2.score, 16600)

        # Check if the score change is created with the correct score change
        score_changes2 = ScoreChange.objects.filter(score=score2)
        # 2*50 + 10*100 + 20*250 = 6100
        self.assertEqual(score_changes2[0].score_change, 6100)
        # 32*250 = 8000
        self.assertEqual(score_changes2[1].score_change, 8000)
        # 10*250 = 2500
        self.assertEqual(score_changes2[2].score_change, 2500)

    def test_initialize_reputation_two_calls(self):
        # This simulates a call that should not recalculate reputation, since optional
        # recalculate argument was not included.
        call_command("initialize_reputation")
        call_command("initialize_reputation")

        # Check if the score is created
        self.assertEqual(Score.objects.count(), 2)

        # Check if the score change is created but not recalculated
        self.assertEqual(ScoreChange.objects.count(), 8)

    def test_initialize_reputation_command_two_calls_recalculate(self):
        # This simulates a recalculation of the reputation.
        call_command("initialize_reputation")
        call_command("initialize_reputation", "--recalculate", True)
        call_command("initialize_reputation")  # This should not recalculate

        # Check if the score is created
        self.assertEqual(Score.objects.count(), 2)

        # Check if the score change is created
        self.assertEqual(ScoreChange.objects.count(), 16)

        # Check if the score is created with the correct score
        score1 = Score.objects.get(
            hub=self.hub1, author=self.user_author.author_profile
        )

        self.assertEqual(score1.score, 23104)
        self.assertEqual(score1.version, 2)

        # Check if the score change is created with the correct score change
        score_changes1 = ScoreChange.objects.filter(
            score=score1, score_version=score1.version
        )
        self.assertEqual(score_changes1.count(), 5)
        self.assertEqual(score_changes1[0].score_change, 23100)
        self.assertEqual(score_changes1[1].score_change, 1)
        self.assertEqual(score_changes1[2].score_change, 1)
        self.assertEqual(score_changes1[3].score_change, 1)
        self.assertEqual(score_changes1[4].score_change, 1)

        # Check if the score is created with the correct score
        score2 = Score.objects.get(
            hub=self.hub2, author=self.user_author.author_profile
        )
        # 2*50 + 10*100 + 52*250 = 14100
        self.assertEqual(score2.score, 16600)
        self.assertEqual(score2.version, 2)

        # Check if the score change is created with the correct score change
        score_changes2 = ScoreChange.objects.filter(
            score=score2, score_version=score2.version
        )

        self.assertEqual(score_changes2.count(), 3)
        # 2*50 + 10*100 + 20*250 = 6100
        self.assertEqual(score_changes2[0].score_change, 6100)
        # 32*250 = 8000
        self.assertEqual(score_changes2[1].score_change, 8000)
        # 10*250 = 2500
        self.assertEqual(score_changes2[2].score_change, 2500)

    @patch("user.models.User.author_profile", new_callable=PropertyMock)
    def test_initialize_reputation_command_missing_author_profile(
        self, mock_author_profile
    ):
        # Mock the author_profile to raise ObjectDoesNotExist
        mock_author_profile.side_effect = ObjectDoesNotExist

        with self.assertRaises(ObjectDoesNotExist):
            self.user_no_author.calculate_hub_scores(1)

    def attribute_paper_to_author(self, user, paper):
        case = AuthorClaimCase.objects.create(
            target_paper=paper, requestor=user, status=APPROVED
        )

        after_approval_flow(case.id)
        user.refresh_from_db()
        paper.refresh_from_db()
