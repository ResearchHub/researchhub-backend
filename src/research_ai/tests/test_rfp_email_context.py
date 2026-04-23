"""Tests for research_ai.services.rfp_email_context."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase

from research_ai.models import Expert, ExpertSearch, SearchExpert
from research_ai.services.rfp_email_context import (
    build_rfp_context,
    get_grant_frontend_url,
    resolve_expert_from_search,
    resolve_grant,
)
from user.tests.helpers import create_random_authenticated_user


class GetGrantFrontendUrlTests(TestCase):
    def test_returns_none_when_grant_none(self):
        self.assertIsNone(get_grant_frontend_url(None))

    def test_returns_none_when_no_unified_document_id(self):
        grant = MagicMock()
        grant.unified_document_id = None
        self.assertIsNone(get_grant_frontend_url(grant))

    def test_returns_none_when_posts_first_returns_none(self):
        grant = MagicMock()
        grant.unified_document_id = 1
        grant.unified_document.posts.first.return_value = None
        self.assertIsNone(get_grant_frontend_url(grant))

    def test_returns_none_when_post_has_no_id_or_slug(self):
        grant = MagicMock()
        grant.unified_document_id = 1
        post = MagicMock()
        post.id = 1
        post.slug = None  # missing slug
        grant.unified_document.posts.first.return_value = post
        self.assertIsNone(get_grant_frontend_url(grant))

    def test_returns_url_when_post_has_id_and_slug(self):
        grant = MagicMock()
        grant.unified_document_id = 1
        post = MagicMock()
        post.id = 42
        post.slug = "my-grant"
        grant.unified_document.posts.first.return_value = post
        url = get_grant_frontend_url(grant)
        self.assertIsNotNone(url)
        self.assertIn("/grant/42/my-grant", url)

    def test_returns_none_on_exception(self):
        grant = MagicMock()
        grant.unified_document_id = 1
        grant.unified_document.posts.first.side_effect = Exception("Broken")
        self.assertIsNone(get_grant_frontend_url(grant))


class BuildRfpContextTests(TestCase):
    def test_returns_empty_dict_when_grant_none(self):
        self.assertEqual(build_rfp_context(None), {})

    @patch("research_ai.services.rfp_email_context.get_grant_frontend_url")
    def test_returns_amount_formatted_k_and_m(self, mock_url):
        mock_url.return_value = "https://example.com/grant/1/slug"
        grant = MagicMock()
        grant.unified_document_id = None
        grant.short_title = "Test"
        grant.description = "Desc"
        grant.amount = Decimal("5000")
        grant.end_date = None
        result = build_rfp_context(grant)
        self.assertEqual(result["amount"], "$5K")
        self.assertEqual(result["title"], "Test")
        self.assertEqual(result["url"], "https://example.com/grant/1/slug")
        self.assertEqual(result["blurb"], "Desc")
        self.assertEqual(result["description_snippet"], "Desc")

    @patch("research_ai.services.rfp_email_context.get_grant_frontend_url")
    def test_returns_amount_millions(self, mock_url):
        mock_url.return_value = ""
        grant = MagicMock()
        grant.unified_document_id = None
        grant.short_title = ""
        grant.description = ""
        grant.amount = Decimal("2000000")
        grant.end_date = None
        result = build_rfp_context(grant)
        self.assertEqual(result["amount"], "$2M")

    @patch("research_ai.services.rfp_email_context.get_grant_frontend_url")
    def test_returns_deadline_formatted(self, mock_url):
        mock_url.return_value = ""
        grant = MagicMock()
        grant.unified_document_id = None
        grant.short_title = ""
        grant.description = ""
        grant.amount = None
        grant.end_date = datetime(2025, 6, 15)
        result = build_rfp_context(grant)
        self.assertEqual(result["deadline"], "June 15, 2025")

    @patch("research_ai.services.rfp_email_context.get_grant_frontend_url")
    def test_description_snippet_length_respected(self, mock_url):
        mock_url.return_value = ""
        grant = MagicMock()
        grant.unified_document_id = None
        grant.short_title = ""
        grant.description = "A" * 1000
        grant.amount = None
        grant.end_date = None
        result = build_rfp_context(grant, description_snippet_length=100)
        self.assertEqual(len(result["description_snippet"]), 100)
        self.assertEqual(len(result["blurb"]), 100)

    def test_returns_empty_dict_on_exception(self):
        grant = MagicMock()
        grant.unified_document_id = 1
        grant.unified_document.get_document.side_effect = Exception("Broken")
        grant.short_title = None
        grant.description = None
        grant.amount = None
        grant.end_date = None
        self.assertEqual(build_rfp_context(grant), {})


class ResolveExpertFromSearchTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("resolve_user")

    def test_returns_none_when_expert_search_none(self):
        self.assertIsNone(resolve_expert_from_search(None, "a@b.com"))

    def test_returns_none_when_no_search_experts(self):
        search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Q",
            status=ExpertSearch.Status.COMPLETED,
            expert_results=[],
        )
        self.assertIsNone(resolve_expert_from_search(search, "a@b.com"))

    def test_returns_none_when_email_empty(self):
        search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Q",
            status=ExpertSearch.Status.COMPLETED,
            expert_results=[],
        )
        ex = Expert.objects.create(email="a@b.com", honorific="Dr", first_name="A")
        SearchExpert.objects.create(expert_search=search, expert=ex, position=0)
        self.assertIsNone(resolve_expert_from_search(search, ""))
        self.assertIsNone(resolve_expert_from_search(search, "   "))

    def test_returns_expert_when_email_matches(self):
        search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Q",
            status=ExpertSearch.Status.COMPLETED,
            expert_results=[],
        )
        ex = Expert.objects.create(
            email="jane@example.com",
            honorific="Dr",
            first_name="Jane",
            affiliation="MIT",
            expertise="ML",
            notes="n",
            academic_title="Prof",
        )
        SearchExpert.objects.create(expert_search=search, expert=ex, position=0)
        result = resolve_expert_from_search(search, "jane@example.com")
        self.assertIsNotNone(result)
        self.assertEqual(result["email"], "jane@example.com")
        self.assertEqual(result["academic_title"], "Prof")
        self.assertEqual(result["affiliation"], "MIT")
        self.assertEqual(result["expertise"], "ML")
        self.assertEqual(result["notes"], "n")
        self.assertEqual(result["expert_id"], ex.id)

    def test_returns_expert_when_email_matches_case_insensitive(self):
        search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Q",
            status=ExpertSearch.Status.COMPLETED,
            expert_results=[],
        )
        ex = Expert.objects.create(
            email="jane@example.com",
            honorific="Dr",
            first_name="Jane",
        )
        SearchExpert.objects.create(expert_search=search, expert=ex, position=0)
        result = resolve_expert_from_search(search, "  jane@example.com  ")
        self.assertEqual(result["email"], "jane@example.com")

    def test_returns_none_when_no_match(self):
        search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Q",
            status=ExpertSearch.Status.COMPLETED,
            expert_results=[],
        )
        ex = Expert.objects.create(email="a@b.com", honorific="Dr", first_name="A")
        SearchExpert.objects.create(expert_search=search, expert=ex, position=0)
        self.assertIsNone(resolve_expert_from_search(search, "other@b.com"))


class ResolveGrantTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("grant_user")

    def test_returns_none_when_expert_search_none(self):
        self.assertIsNone(resolve_grant(expert_search=None))

    def test_returns_none_when_no_unified_document_id(self):
        search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Q",
            status=ExpertSearch.Status.COMPLETED,
            unified_document_id=None,
        )
        self.assertIsNone(resolve_grant(expert_search=search))

    @patch("research_ai.services.rfp_email_context.ExpertSearch")
    def test_returns_grant_when_unified_document_has_grants(self, mock_expert_search):
        mock_grant = MagicMock()
        mock_search = MagicMock()
        mock_search.unified_document_id = 1
        mock_search.unified_document.grants.first.return_value = mock_grant
        result = resolve_grant(expert_search=mock_search)
        self.assertIs(result, mock_grant)

    def test_returns_none_when_grants_first_raises(self):
        mock_search = MagicMock()
        mock_search.unified_document_id = 1
        mock_search.unified_document.grants.first.side_effect = Exception("DB error")
        result = resolve_grant(expert_search=mock_search)
        self.assertIsNone(result)
