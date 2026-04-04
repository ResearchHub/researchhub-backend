from unittest.mock import MagicMock, patch

from django.test import TestCase

from ai_peer_review.services.researcher_external_context import (
    build_researcher_external_context,
)
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.tests.helpers import create_random_default_user


class ResearcherExternalContextTests(TestCase):
    def test_returns_empty_when_no_owner(self):
        ud = MagicMock()
        ud.created_by = None
        self.assertEqual(build_researcher_external_context(ud), "")

    def test_returns_empty_when_no_orcid_on_author(self):
        user = create_random_default_user("ext_ctx_no_orcid")
        author = user.author_profile
        author.orcid_id = ""
        author.save()
        post = create_post(created_by=user, document_type=PREREGISTRATION)
        ud = post.unified_document
        self.assertEqual(build_researcher_external_context(ud), "")

    @patch("ai_peer_review.services.researcher_external_context.OrcidClient")
    @patch("ai_peer_review.services.researcher_external_context.OpenAlex")
    def test_combines_openalex_and_orcid_works(self, mock_openalex_cls, mock_orcid_cls):
        user = create_random_default_user("ext_ctx_full")
        author = user.author_profile
        author.orcid_id = "0000-0001-2345-6789"
        author.save()
        post = create_post(created_by=user, document_type=PREREGISTRATION)
        ud = post.unified_document

        mock_oa = MagicMock()
        mock_oa.get_author_via_orcid.return_value = {
            "display_name": "Jane Doe",
            "works_count": 42,
            "cited_by_count": 100,
            "summary_stats": {"h_index": 12},
            "topics": [{"display_name": "Cardiology"}],
        }
        mock_openalex_cls.return_value = mock_oa

        mock_oc = MagicMock()
        mock_oc.get_works.return_value = {
            "group": [
                {
                    "work-summary": [
                        {
                            "title": {"title": {"value": "A Paper"}},
                            "publication-date": {"year": {"value": "2021"}},
                        }
                    ]
                }
            ]
        }
        mock_orcid_cls.return_value = mock_oc

        text = build_researcher_external_context(ud)
        self.assertIn("0000-0001-2345-6789", text)
        self.assertIn("Jane Doe", text)
        self.assertIn("h-index", text)
        self.assertIn("A Paper", text)
        self.assertIn("(2021)", text)

    @patch("ai_peer_review.services.researcher_external_context.OrcidClient")
    @patch("ai_peer_review.services.researcher_external_context.OpenAlex")
    def test_returns_empty_when_openalex_fails_and_no_works(
        self, mock_oa_cls, mock_oc_cls
    ):
        user = create_random_default_user("ext_ctx_fail")
        author = user.author_profile
        author.orcid_id = "0000-0001-2345-6789"
        author.save()
        post = create_post(created_by=user, document_type=PREREGISTRATION)
        ud = post.unified_document

        mock_oa_cls.return_value.get_author_via_orcid.side_effect = RuntimeError(
            "network"
        )
        mock_oc_cls.return_value.get_works.return_value = {}

        self.assertEqual(build_researcher_external_context(ud), "")

    @patch("ai_peer_review.services.researcher_external_context.OrcidClient")
    @patch("ai_peer_review.services.researcher_external_context.OpenAlex")
    def test_truncates_when_over_max_chars(self, mock_oa_cls, mock_oc_cls):
        user = create_random_default_user("ext_ctx_trunc")
        author = user.author_profile
        author.orcid_id = "0000-0001-2345-6789"
        author.save()
        post = create_post(created_by=user, document_type=PREREGISTRATION)
        ud = post.unified_document

        long_name = "X" * 5000
        mock_oa_cls.return_value.get_author_via_orcid.return_value = {
            "display_name": long_name,
            "works_count": 1,
        }
        mock_oc_cls.return_value.get_works.return_value = {}

        text = build_researcher_external_context(ud, max_chars=500)
        self.assertTrue(text.endswith("[TRUNCATED]"))
        self.assertLessEqual(len(text), 520)
