from django.test import TestCase

from ai_peer_review.services.author_context import build_author_context_snippet
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
)
from user.models import Author
from user.tests.helpers import create_random_default_user


class AuthorContextSnippetTests(TestCase):
    def test_includes_orcid_and_headline_when_author_exists(self):
        user = create_random_default_user("ctx_orcid")
        Author.objects.create(
            user=user,
            first_name="A",
            last_name="B",
            orcid_id="0000-0002-1825-0097",
            headline="Lab PI",
            description="",
        )
        post = create_post(created_by=user, document_type=PREREGISTRATION)
        ud = post.unified_document
        text = build_author_context_snippet(ud)
        self.assertIn("ORCID:", text)
        self.assertIn("0000-0002-1825-0097", text)
        self.assertIn("Headline:", text)
        self.assertIn("Lab PI", text)
