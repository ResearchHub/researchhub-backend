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


class ModeratorTests(APITestCase):

    def test_moderator_can_view_details(self):
        self.user = create_user(
            email="mod@example.com",
            first_name="Moderator",
            last_name="mod",
            moderator=True,
        )

        self.client.force_authenticate(user=self.user)

        url = f"/api/moderator/{self.user.id}/user_details/"
        response = self.client.get(url, {})
        self.assertIn("id", response.data)

    def test_non_moderator_cannot_view_details(self):
        self.user = create_user(
            email="user@example.com",
            first_name="Moderator",
            last_name="user",
            moderator=False,
        )

        self.client.force_authenticate(user=self.user)

        url = f"/api/moderator/{self.user.id}/user_details/"
        response = self.client.get(url, {})
        self.assertNotIn("id", response.data)
