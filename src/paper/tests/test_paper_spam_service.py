import csv
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.management import CommandError, call_command
from django.test import TestCase

from paper.models import Paper
from paper.services.paper_spam_service import (
    ClassifyScope,
    PaperSpamService,
    Verdict,
)
from paper.tests.helpers import create_paper
from research_ai.services.message_screening.jev_client import (
    Decision,
    DecisionError,
    JevClient,
)
from user.tests.helpers import create_random_default_user

ABSTRACT = (
    "We measure the thermal conductivity of layered graphene oxide films "
    "across a range of humidities and compare the results with a "
    "phonon transport model."
)


def make_paper(uploader, **fields):
    paper = create_paper(
        title=fields.pop("title", "Thermal transport in graphene oxide films"),
        uploaded_by=uploader,
        raw_authors=fields.pop("raw_authors", [{"first_name": "A", "last_name": "B"}]),
    )
    defaults = {
        "abstract": ABSTRACT,
        "doi": f"10.1234/{paper.id}",
        "pdf_url": "https://example.edu/paper.pdf",
    }
    for name, value in {**defaults, **fields}.items():
        setattr(paper, name, value)
    paper.save()
    return paper


def jev(answers=None, error=None):
    client = MagicMock(spec=JevClient)
    client.model = "typesafe/jev"
    if error:
        client.decide.side_effect = error
    else:
        client.decide.return_value = Decision(
            model="typesafe/jev", answers=answers, cost_microusd=40
        )
    return client


class PaperSpamServiceTest(TestCase):
    def setUp(self):
        self.user = create_random_default_user("uploader")

    def scores(self, classify=ClassifyScope.NONE, client=None):
        service = PaperSpamService(client=client or jev({}))
        return {s.paper.id: s for s in service.score_all(classify=classify)}

    def test_genuine_paper_is_kept(self):
        # Arrange
        paper = make_paper(self.user)

        # Act
        score = self.scores()[paper.id]

        # Assert
        self.assertEqual(score.verdict, Verdict.KEEP)

    def test_promotional_paper_from_flagged_uploader_is_spam(self):
        # Arrange
        self.user.probable_spammer = True
        self.user.save()
        paper = make_paper(
            self.user,
            title="Best online casino bonus www.spin-win.xyz",
            raw_authors=[],
            abstract="",
            doi=None,
        )

        # Act
        score = self.scores()[paper.id]

        # Assert
        self.assertEqual(score.verdict, Verdict.SPAM)
        self.assertIn("uploader_flagged", score.reasons)
        self.assertIn("link_in_title", score.reasons)
        self.assertIn("promotional_terms:online casino", score.reasons)

    def test_research_on_commercial_topics_is_kept(self):
        # Arrange
        paper = make_paper(
            self.user,
            title="Payday lending, consumer loans and CBD use among casino workers",
        )

        # Act
        score = self.scores()[paper.id]

        # Assert
        self.assertEqual(score.verdict, Verdict.KEEP)

    def test_phone_number_and_thin_metadata_go_to_review(self):
        # Arrange
        paper = make_paper(
            self.user,
            title="Flight bookings +1 800 555 0199",
            abstract="",
            doi=None,
        )

        # Act
        score = self.scores()[paper.id]

        # Assert
        self.assertEqual(score.verdict, Verdict.REVIEW)
        self.assertIn("contact_details", score.reasons)
        self.assertIn("thin_metadata", score.reasons)

    def test_years_and_scholarly_links_are_not_flagged(self):
        # Arrange
        paper = make_paper(
            self.user,
            abstract=ABSTRACT
            + " Data from 2019 2020 2021 at https://doi.org/10.1/x and "
            "https://arxiv.org/abs/1234.5678.",
        )

        # Act
        score = self.scores()[paper.id]

        # Assert
        self.assertEqual(score.reasons, ["new_account"])

    def test_burst_uploads_and_shared_titles_are_flagged(self):
        # Arrange
        for i in range(10):
            make_paper(self.user, title=f"Paper {i}")
        others = [create_random_default_user(f"other{i}") for i in range(2)]
        shared = [make_paper(u, title="Same Title") for u in [self.user, *others]]

        # Act
        scores = self.scores()

        # Assert
        self.assertIn("burst_uploader", scores[shared[0].id].reasons)
        self.assertNotIn("burst_uploader", scores[shared[1].id].reasons)
        self.assertIn("shared_title:3", scores[shared[1].id].reasons)

    def test_only_live_user_uploads_are_scored(self):
        # Arrange
        kept = make_paper(self.user)
        make_paper(self.user, is_removed=True)
        make_paper(self.user, retrieved_from_external_source=True)
        make_paper(None)

        # Act
        scores = self.scores()

        # Assert
        self.assertEqual(list(scores), [kept.id])

    def test_classifier_can_mark_a_clean_looking_paper_as_spam(self):
        # Arrange
        paper = make_paper(self.user)
        client = jev({"not_research": 0.95, "promotional": 0.2})

        # Act
        score = self.scores(ClassifyScope.ALL, client)[paper.id]

        # Assert
        self.assertEqual(score.verdict, Verdict.SPAM)
        self.assertEqual(score.cost_microusd, 40)
        state = client.decide.call_args.args[0]
        self.assertEqual(state["title"], paper.title)
        self.assertEqual(state["authors"], ["A B"])

    def test_unclear_scope_classifies_only_review_papers(self):
        # Arrange
        make_paper(self.user)
        unclear = make_paper(self.user, title="Call +1 800 555 0199", doi=None)
        client = jev({"not_research": 0.1, "promotional": 0.1})

        # Act
        scores = self.scores(ClassifyScope.UNCLEAR, client)

        # Assert
        self.assertEqual(client.decide.call_count, 1)
        self.assertEqual(scores[unclear.id].not_research, 0.1)

    def test_classifier_error_keeps_the_heuristic_verdict(self):
        # Arrange
        paper = make_paper(self.user)
        client = jev(error=DecisionError("timeout"))

        # Act
        score = self.scores(ClassifyScope.ALL, client)[paper.id]

        # Assert
        self.assertEqual(score.verdict, Verdict.KEEP)
        self.assertEqual(score.classifier_error, "timeout")


class ScoreSpamPapersCommandTest(TestCase):
    def setUp(self):
        self.user = create_random_default_user("uploader")
        self.user.probable_spammer = True
        self.user.save()
        self.spam = make_paper(
            self.user, title="=HYPERLINK payday loans www.x.com", abstract=""
        )
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.output = Path(self.dir.name) / "scores.csv"

    def read(self, path):
        with path.open() as file:
            return list(csv.DictReader(file))

    @patch.object(JevClient, "from_settings", return_value=None)
    def test_writes_scores_and_changes_nothing(self, _):
        # Act
        call_command("score_spam_papers", output=str(self.output), stdout=MagicMock())

        # Assert
        [row] = self.read(self.output)
        self.assertEqual(row["paper_id"], str(self.spam.id))
        self.assertEqual(row["verdict"], "spam")
        self.assertTrue(row["title"].startswith("'="))
        [uploader] = self.read(Path(self.dir.name) / "scores_uploaders.csv")
        self.assertEqual(uploader["spam"], "1")
        self.assertEqual(uploader["uploader_flagged"], "True")
        self.assertFalse(Paper.objects.get(id=self.spam.id).is_removed)

    @patch.object(JevClient, "from_settings", return_value=None)
    def test_classify_without_api_key_fails(self, _):
        # Act / Assert
        with self.assertRaises(CommandError):
            call_command(
                "score_spam_papers", output=str(self.output), classify="unclear"
            )
        self.assertFalse(self.output.exists())
