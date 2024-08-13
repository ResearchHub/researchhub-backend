from django.test import TestCase

from paper.related_models.authorship_model import Authorship
from paper.related_models.paper_model import Paper
from user.tests.helpers import create_user


class AuthorModelsTests(TestCase):
    def setUp(self):
        self.user = create_user(
            email="random@researchhub.com",
            first_name="random",
            last_name="user",
        )

        paper1 = Paper.objects.create(
            title="title1",
            citations=10,
            is_open_access=True,
        )

        paper2 = Paper.objects.create(
            title="title2",
            citations=20,
            is_open_access=False,
        )

        Authorship.objects.create(author=self.user.author_profile, paper=paper1)
        Authorship.objects.create(author=self.user.author_profile, paper=paper2)

    def test_citation_count_property(self):
        self.assertEqual(self.user.author_profile.citation_count, 30)

    def test_paper_count_property(self):
        self.assertEqual(self.user.author_profile.paper_count, 2)

    def test_open_access_pct_property(self):
        self.assertEqual(self.user.author_profile.open_access_pct, 0.5)

    def test_achievements(self):
        self.assertIn("CITED_AUTHOR", self.user.author_profile.achievements)
