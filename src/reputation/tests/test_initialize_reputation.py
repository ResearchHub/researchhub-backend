import json
from unittest.mock import PropertyMock, patch

from django.core.exceptions import ObjectDoesNotExist
from django.core.management import call_command
from django.test import TestCase

from discussion.reaction_models import Vote
from discussion.tests.helpers import create_rh_comment, create_vote
from paper.models import Paper
from paper.openalex_util import process_openalex_works
from reputation.models import AlgorithmVariables, Score, ScoreChange
from researchhub_case.constants.case_constants import APPROVED
from researchhub_case.models import AuthorClaimCase
from researchhub_case.tasks import after_approval_flow
from user.models import User
from utils.openalex import OpenAlex


class InitializeReputationCommandTestCase(TestCase):
    @patch.object(OpenAlex, "get_authors")
    def setUp(self, mock_get_authors):
        # Add user, an author is automatically created for this user.
        self.user_author = User.objects.create_user(username="user1", password="pass1")
        self.user_basic = User.objects.create_user(username="user2", password="pass2")
        self.user_no_author = User.objects.create_user(
            username="user3", password="pass3"
        )

        with open("./paper/tests/openalex_works.json", "r") as file:
            response = json.load(file)
            self.works = response.get("results")

        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(self.works)

            dois = [work.get("doi") for work in self.works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]
            created_papers = Paper.objects.filter(doi__in=dois)
            self.paper1 = created_papers[0]
            self.paper2 = created_papers[1]

            self.paper1_hub = self.paper1.unified_document.get_primary_hub()
            self.paper2_hub = self.paper2.unified_document.get_primary_hub()

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
            json.dumps((200, 2800000)): 1,
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
            hub=self.paper1_hub,
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
            hub=self.paper1_hub,
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
            hub=self.paper2_hub,
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
            hub=self.paper2_hub,
        )

        # Create comments
        self.comment1 = create_rh_comment(
            paper=self.paper1, created_by=self.user_author
        )
        self.comment2 = create_rh_comment(
            paper=self.paper1, created_by=self.user_author
        )

        # Upvote comment 1
        create_vote(self.user_author, self.comment1, Vote.UPVOTE)
        create_vote(self.user_basic, self.comment1, Vote.UPVOTE)

        # Downvote comment 2
        create_vote(self.user_author, self.comment2, Vote.UPVOTE)

        # Upvote paper 1
        create_vote(self.user_author, self.paper1, Vote.UPVOTE)

        # Add author claim
        self.attribute_paper_to_author(self.user_author, self.paper1)
        self.attribute_paper_to_author(self.user_author, self.paper2)

    def test_initialize_reputation_command(self):
        call_command("initialize_reputation")

        # Check if the score is created with the correct score
        score1 = Score.objects.get(
            hub=self.paper1_hub, author=self.user_author.author_profile
        )

        self.assertEqual(score1.score, 194250)

        # Check if the score change is created with the correct score change
        score_changes1 = ScoreChange.objects.filter(score=score1).order_by(
            "-score_change"
        )
        self.assertEqual(score_changes1.count(), 5)
        self.assertEqual(score_changes1[0].score_change, 194246)
        self.assertEqual(score_changes1[1].score_change, 1)
        self.assertEqual(score_changes1[2].score_change, 1)
        self.assertEqual(score_changes1[3].score_change, 1)
        self.assertEqual(score_changes1[4].score_change, 1)

        # Check if the score is created with the correct score
        score2 = Score.objects.get(
            hub=self.paper2_hub, author=self.user_author.author_profile
        )
        self.assertEqual(score2.score, 208275)

        # Check if the score change is created with the correct score change
        score_changes2 = ScoreChange.objects.filter(score=score2)
        self.assertEqual(score_changes2.count(), 1)
        self.assertEqual(score_changes2[0].score_change, 208275)

    def test_initialize_reputation_two_calls(self):
        # This simulates a call that should not recalculate reputation, since optional
        # recalculate argument was not included.
        call_command("initialize_reputation")
        call_command("initialize_reputation")

        # Check if the score is created
        self.assertEqual(Score.objects.count(), 2)

        # Check if the score change is created but not recalculated
        self.assertEqual(ScoreChange.objects.count(), 6)

    def test_initialize_reputation_command_two_calls_recalculate(self):
        # This simulates a recalculation of the reputation.
        call_command("initialize_reputation")
        call_command("initialize_reputation", "--recalculate", True)
        call_command("initialize_reputation")  # This should not recalculate

        # Check if the score is created with the correct score
        score1 = Score.objects.get(
            hub=self.paper1_hub, author=self.user_author.author_profile
        )

        self.assertEqual(score1.score, 194250)
        self.assertEqual(score1.version, 2)

        # Check if the score change is created with the correct score change
        score_changes1 = ScoreChange.objects.filter(
            score=score1, score_version=score1.version
        )
        self.assertEqual(score_changes1.count(), 5)
        self.assertEqual(score_changes1[0].score_change, 194246)
        self.assertEqual(score_changes1[1].score_change, 1)
        self.assertEqual(score_changes1[2].score_change, 1)
        self.assertEqual(score_changes1[3].score_change, 1)
        self.assertEqual(score_changes1[4].score_change, 1)

        # Check if the score is created with the correct score
        score2 = Score.objects.get(
            hub=self.paper2_hub, author=self.user_author.author_profile
        )
        self.assertEqual(score2.score, 208275)
        self.assertEqual(score2.version, 2)

        # Check if the score change is created with the correct score change
        score_changes2 = ScoreChange.objects.filter(
            score=score2, score_version=score2.version
        )

        self.assertEqual(score_changes2.count(), 1)
        self.assertEqual(score_changes2[0].score_change, 208275)

    def test_initialize_reputation_command_signals(self):
        call_command("initialize_reputation")
        self.paper1.citations = self.paper1.citations + 100
        self.paper1.save()
        create_vote(self.user_basic, self.paper1, Vote.DOWNVOTE)
        create_vote(self.user_no_author, self.comment1, Vote.DOWNVOTE)

        # Check if the score is created with the correct score
        score1 = Score.objects.get(
            hub=self.paper1_hub, author=self.user_author.author_profile
        )

        self.assertEqual(score1.score, 194348)

        # Check if the score change is created with the correct score change
        score_changes1 = ScoreChange.objects.filter(score=score1).order_by(
            "-score_change"
        )
        self.assertEqual(score_changes1.count(), 8)
        self.assertEqual(score_changes1[0].score_change, 194246)
        self.assertEqual(score_changes1[1].score_change, 100)
        self.assertEqual(score_changes1[2].score_change, 1)
        self.assertEqual(score_changes1[3].score_change, 1)
        self.assertEqual(score_changes1[4].score_change, 1)
        self.assertEqual(score_changes1[5].score_change, 1)
        self.assertEqual(score_changes1[6].score_change, -1)
        self.assertEqual(score_changes1[7].score_change, -1)

        # Check if the score is created with the correct score
        score2 = Score.objects.get(
            hub=self.paper2_hub, author=self.user_author.author_profile
        )
        self.assertEqual(score2.score, 208275)

        # Check if the score change is created with the correct score change
        score_changes2 = ScoreChange.objects.filter(score=score2)
        self.assertEqual(score_changes2.count(), 1)
        self.assertEqual(score_changes2[0].score_change, 208275)

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
