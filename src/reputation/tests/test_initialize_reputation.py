import json
import os
import uuid
from unittest.mock import PropertyMock, patch

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.management import call_command
from django.test import TestCase

from discussion.models import Vote
from discussion.tests.helpers import create_vote
from paper.models import Paper
from paper.openalex_util import process_openalex_works
from paper.related_models.authorship_model import Authorship
from paper.related_models.citation_model import Citation
from reputation.models import AlgorithmVariables, Score, ScoreChange
from researchhub_comment.tests.helpers import create_rh_comment
from user.models import User
from utils.openalex import OpenAlex


class InitializeReputationCommandTestCase(TestCase):
    def setUp(self):
        # Add user, an author is automatically created for this user.
        self.user_author = User.objects.create_user(
            username="user1", password=uuid.uuid4().hex
        )
        self.user_basic = User.objects.create_user(
            username="user2", password=uuid.uuid4().hex
        )
        self.user_no_author = User.objects.create_user(
            username="user3", password=uuid.uuid4().hex
        )

    def test_initialize_reputation_command(self):
        self.setup_papers_algo_hubs(False)

        call_command("initialize_reputation")

        # Check if the score is created
        self.assertEqual(Score.objects.count(), 2)

        # Check if the score change is created
        self.assertEqual(ScoreChange.objects.count(), 6)

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

    def test_initialize_reputation_command_review_paper(self):
        self.setup_papers_algo_hubs(True)

        call_command("initialize_reputation")

        # Check if the score is created
        self.assertEqual(Score.objects.count(), 2)

        # Check if the score change is created
        self.assertEqual(ScoreChange.objects.count(), 6)

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
        self.assertEqual(score2.score, 41655)

        # Check if the score change is created with the correct score change
        score_changes2 = ScoreChange.objects.filter(score=score2)
        self.assertEqual(score_changes2.count(), 1)
        self.assertEqual(score_changes2[0].score_change, 41655)

    def test_initialize_reputation_command_two_calls_recalculate(self):
        self.setup_papers_algo_hubs(False)

        # This simulates a recalculation of the reputation.
        call_command("initialize_reputation")
        call_command("initialize_reputation")

        # Check if the score is created
        self.assertEqual(Score.objects.count(), 2)

        # Check if the score change is created
        self.assertEqual(ScoreChange.objects.count(), 6)

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
        # Get some of score changes and check if it equals score score
        self.assertEqual(
            sum([score_change.score_change for score_change in score_changes1]),
            score1.score,
        )

        # Check if the score is created with the correct score
        score2 = Score.objects.get(
            hub=self.paper2_hub, author=self.user_author.author_profile
        )
        self.assertEqual(score2.score, 208275)

        # Check if the score change is created with the correct score change
        score_changes2 = ScoreChange.objects.filter(score=score2)

        self.assertEqual(score_changes2.count(), 1)
        self.assertEqual(score_changes2[0].score_change, 208275)

    def test_initialize_reputation_command_two_calls_changes_in_between(self):
        self.setup_papers_algo_hubs(False)

        call_command("initialize_reputation")
        self.paper1.citations = self.paper1.citations + 100
        self.paper1.save()
        source = Citation.objects.get(paper=self.paper1).source
        Citation.objects.create(
            paper=self.paper1,
            total_citation_count=self.paper1.citations,
            citation_change=100,
            source=source,
        )
        create_vote(self.user_basic, self.paper1, Vote.DOWNVOTE)
        create_vote(self.user_no_author, self.comment1, Vote.DOWNVOTE)
        call_command("initialize_reputation")

        # Check if the score is created
        self.assertEqual(Score.objects.count(), 2)

        # Check if the score change is created
        self.assertEqual(ScoreChange.objects.count(), 9)

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

    # Test that that increasing the algorithm version will not clear reputation change
    def test_initialize_reputation_command_algorithm_version(self):
        # Mock ALGORITHM_VERSION to 1
        with patch("reputation.related_models.score.ALGORITHM_VERSION", 1):
            self.setup_papers_algo_hubs(False)

            call_command("initialize_reputation")

            # Check if the score is created
            self.assertEqual(Score.objects.count(), 2)

            # Check if the score change is created
            self.assertEqual(ScoreChange.objects.count(), 6)

            # Check if the score is created with the correct score
            score1 = Score.objects.get(
                hub=self.paper1_hub, author=self.user_author.author_profile
            )

            self.assertEqual(score1.score, 194250)

            # Check if the score change is created with the correct score change
            score_changes1 = ScoreChange.objects.filter(
                score=score1, algorithm_version=1
            ).order_by("-score_change")
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
            score_changes2 = ScoreChange.objects.filter(
                score=score2, algorithm_version=1
            )
            self.assertEqual(score_changes2.count(), 1)
            self.assertEqual(score_changes2[0].score_change, 208275)

        # Mock ALGORITHM_VERSION to 2
        with patch("reputation.related_models.score.ALGORITHM_VERSION", 2):
            call_command("initialize_reputation")

            # Check if the score is created
            self.assertEqual(Score.objects.count(), 2)

            # Check if the score change is created
            self.assertEqual(ScoreChange.objects.count(), 12)

            # Check if the score is created with the correct score
            score1 = Score.objects.get(
                hub=self.paper1_hub, author=self.user_author.author_profile
            )

            self.assertEqual(score1.score, 194250)

            # Check if the score change is created with the correct score change
            score_changes1 = ScoreChange.objects.filter(
                score=score1, algorithm_version=2
            ).order_by("-score_change")
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
            score_changes2 = ScoreChange.objects.filter(
                score=score2, algorithm_version=2
            )
            self.assertEqual(score_changes2.count(), 1)
            self.assertEqual(score_changes2[0].score_change, 208275)

    @patch("user.models.User.author_profile", new_callable=PropertyMock)
    def test_initialize_reputation_command_missing_author_profile(
        self, mock_author_profile
    ):
        # Mock the author_profile to raise ObjectDoesNotExist
        mock_author_profile.side_effect = ObjectDoesNotExist

        with self.assertRaises(ObjectDoesNotExist):
            self.user_no_author.calculate_hub_scores()

    @patch.object(OpenAlex, "get_authors")
    def setup_papers_algo_hubs(self, create_review_paper, mock_get_authors):
        works_file_path = os.path.join(
            settings.BASE_DIR, "paper", "tests", "openalex_works.json"
        )
        with open(works_file_path, "r") as file:
            response = json.load(file)
            self.works = sorted(
                response.get("results"), key=lambda x: x.get("citations") or 0
            )

        authors_file_path = os.path.join(
            settings.BASE_DIR, "paper", "tests", "openalex_authors.json"
        )
        with open(authors_file_path, "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)
            process_openalex_works(self.works)

            created_papers = Paper.objects.all().order_by("citations")
            self.paper1 = created_papers[0]

            self.paper2 = created_papers[1]
            if create_review_paper:
                self.paper2.work_type = "review"
                self.paper2.save()

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

        old_citation_bins = {
            json.dumps((0, 2)): 5,
            json.dumps((2, 12)): 10,
            json.dumps((12, 200)): 25,
            json.dumps((200, 2800)): 10,
        }

        citation_bins = {
            json.dumps((0, 2)): 50,
            json.dumps((2, 12)): 100,
            json.dumps((12, 200)): 250,
            json.dumps((200, 280000)): 1,
        }

        # Create an old unused algorithm_variables row
        AlgorithmVariables.objects.create(
            variables={
                "citations": {
                    "bins": old_citation_bins,
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
                    "bins": old_citation_bins,
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
        Authorship.objects.get_or_create(
            author=self.user_author.author_profile,
            paper=self.paper1,
        )
        Authorship.objects.get_or_create(
            author=self.user_author.author_profile,
            paper=self.paper2,
        )
