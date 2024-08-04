import json
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APITestCase

from paper.openalex_util import process_openalex_works
from paper.related_models.authorship_model import Authorship
from paper.related_models.paper_model import Paper
from reputation.models import Score
from user.models import UserVerification
from user.related_models.author_model import Author
from user.tests.helpers import (
    create_random_authenticated_user,
    create_random_default_user,
    create_user,
)
from utils.openalex import OpenAlex
from utils.test_helpers import (
    get_authenticated_get_response,
    get_authenticated_patch_response,
)


class AuthorApiTests(APITestCase):
    def setUp(self):
        self.user_with_published_works = create_user(
            email="random@researchhub.com",
            first_name="Yang",
            last_name="Wang",
        )

        paper1 = Paper.objects.create(
            title="title1",
            citations=10,
        )
        paper2 = Paper.objects.create(
            title="title2",
            citations=20,
        )
        Authorship.objects.create(
            author=self.user_with_published_works.author_profile, paper=paper1
        )
        Authorship.objects.create(
            author=self.user_with_published_works.author_profile, paper=paper2
        )

    def test_get_author_summary_stats(self):
        url = f"/api/author/{self.user_with_published_works.author_profile.id}/summary_stats/"
        response = self.client.get(url, {})
        self.assertIn("summary_stats", response.data)

    def test_get_achievements(self):
        url = f"/api/author/{self.user_with_published_works.author_profile.id}/achievements/"
        response = self.client.get(url, {})
        self.assertIn("achievements", response.data)

    def test_get_profile(self):
        url = f"/api/author/{self.user_with_published_works.author_profile.id}/profile/"
        response = self.client.get(url, {})
        self.assertIn("profile", response.data)
