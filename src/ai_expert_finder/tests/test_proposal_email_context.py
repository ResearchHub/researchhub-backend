"""Tests for ai_expert_finder.services.proposal_email_context."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase

from ai_expert_finder.services.proposal_email_context import (
    _creator_display_name,
    _format_amount_raised,
    _fundraise_email_fields,
    _resolve_post_for_proposal_context,
    build_proposal_context,
    get_proposal_frontend_url,
)


class GetProposalFrontendUrlTests(TestCase):
    def test_returns_none_when_none(self):
        self.assertIsNone(get_proposal_frontend_url(None))

    def test_returns_url_from_unified_document_frontend_view_link(self):
        udoc = MagicMock()
        udoc.unified_document = udoc
        udoc.frontend_view_link.return_value = (
            "https://www.researchhub.com/post/10/my-slug"
        )
        url = get_proposal_frontend_url(udoc)
        self.assertEqual(url, "https://www.researchhub.com/post/10/my-slug")

    def test_returns_url_from_post_id_slug_when_no_frontend_view_link(self):
        post = MagicMock()
        post.unified_document = None
        post.get_document = MagicMock(return_value=None)
        post.id = 5
        post.slug = "prereg-2025"
        url = get_proposal_frontend_url(post)
        self.assertIn("/fund/5/prereg-2025", url)

    def test_returns_none_when_post_id_or_slug_missing(self):
        post = MagicMock()
        post.unified_document = None
        post.get_document = MagicMock(return_value=None)
        post.id = None
        post.slug = "x"
        self.assertIsNone(get_proposal_frontend_url(post))
        post.id = 1
        post.slug = None
        self.assertIsNone(get_proposal_frontend_url(post))

    def test_returns_none_when_frontend_view_link_raises(self):
        udoc = MagicMock()
        udoc.unified_document = udoc
        udoc.frontend_view_link = MagicMock(side_effect=RuntimeError("link error"))
        self.assertIsNone(get_proposal_frontend_url(udoc))


class FormatAmountRaisedTests(TestCase):
    def test_none_or_non_positive_returns_empty(self):
        self.assertEqual(_format_amount_raised(None), "")
        self.assertEqual(_format_amount_raised(0), "")
        self.assertEqual(_format_amount_raised(-1), "")

    def test_small_amount(self):
        self.assertEqual(_format_amount_raised(42.3), "$42")

    def test_thousands_and_millions(self):
        self.assertEqual(_format_amount_raised(1500), "$1K")
        self.assertEqual(_format_amount_raised(2_500_000), "$2M")

    def test_fallback_when_int_round_raises(self):
        # NaN passes the <= 0 guard but int(round(nan)) raises ValueError; except formats with .0f.
        self.assertEqual(_format_amount_raised(float("nan")), "$nan")


class ResolvePostForProposalContextTests(TestCase):
    def test_returns_input_when_title_set(self):
        post = MagicMock()
        post.title = "Has title"
        udoc = MagicMock()
        self.assertIs(_resolve_post_for_proposal_context(post, udoc), post)

    def test_returns_get_document_when_no_title(self):
        udoc = MagicMock()
        inner_post = MagicMock()
        udoc.get_document.return_value = inner_post
        wrapper = MagicMock()
        wrapper.title = None
        self.assertIs(
            _resolve_post_for_proposal_context(wrapper, udoc),
            inner_post,
        )

    def test_returns_none_when_no_title_and_no_udoc(self):
        w = MagicMock()
        w.title = None
        self.assertIsNone(_resolve_post_for_proposal_context(w, None))


class CreatorDisplayNameTests(TestCase):
    def test_empty_when_no_user(self):
        self.assertEqual(_creator_display_name(None), "")

    def test_first_last(self):
        u = MagicMock()
        u.first_name = "A"
        u.last_name = "B"
        u.email = "a@b.com"
        self.assertEqual(_creator_display_name(u), "A B")

    def test_falls_back_to_email(self):
        u = MagicMock()
        u.first_name = ""
        u.last_name = ""
        u.email = "only@email.com"
        self.assertEqual(_creator_display_name(u), "only@email.com")


class FundraiseEmailFieldsTests(TestCase):
    def test_empty_when_no_udoc(self):
        empty = {
            "goal_amount": "",
            "amount_raised": "",
            "contributor_count": "",
            "deadline": "",
        }
        self.assertEqual(_fundraise_email_fields(None), empty)

    def test_empty_when_udoc_has_no_fundraises_relation(self):
        udoc = MagicMock()
        udoc.fundraises = None
        self.assertEqual(_fundraise_email_fields(udoc)["deadline"], "")

    def test_empty_when_no_fundraise(self):
        udoc = MagicMock()
        udoc.fundraises.first.return_value = None
        self.assertEqual(
            _fundraise_email_fields(udoc)["goal_amount"],
            "",
        )

    def test_populated_from_fundraise(self):
        fundraise = MagicMock()
        fundraise.goal_amount = Decimal("5000")
        fundraise.get_amount_raised.return_value = 1200.0
        summary = MagicMock()
        summary.total = 7
        fundraise.get_contributors_summary.return_value = summary
        fundraise.end_date = datetime(2026, 6, 15, 12, 0, 0)

        udoc = MagicMock()
        udoc.fundraises.first.return_value = fundraise

        out = _fundraise_email_fields(udoc)
        self.assertEqual(out["contributor_count"], "7")
        self.assertIn("K", out["goal_amount"])
        self.assertIn("K", out["amount_raised"])
        self.assertIn("June", out["deadline"])

    def test_contributor_count_empty_when_total_zero(self):
        fundraise = MagicMock()
        fundraise.goal_amount = Decimal("100")
        fundraise.get_amount_raised.return_value = 0.0
        summary = MagicMock()
        summary.total = 0
        fundraise.get_contributors_summary.return_value = summary
        fundraise.end_date = None
        udoc = MagicMock()
        udoc.fundraises.first.return_value = fundraise
        self.assertEqual(_fundraise_email_fields(udoc)["contributor_count"], "")


class BuildProposalContextTests(TestCase):
    def test_returns_empty_dict_when_none(self):
        self.assertEqual(build_proposal_context(None), {})

    def test_returns_title_url_created_by_blurb_from_post(self):
        post = MagicMock()
        post.title = "My Preregistration"
        post.renderable_text = "Body text here."
        post.created_by = None
        post.unified_document = MagicMock()
        post.unified_document.fundraises.first.return_value = None
        post.unified_document.frontend_view_link.return_value = (
            "https://www.researchhub.com/post/1/slug"
        )
        result = build_proposal_context(post)
        self.assertEqual(result["title"], "My Preregistration")
        self.assertEqual(result["url"], "https://www.researchhub.com/post/1/slug")
        self.assertEqual(result["created_by_name"], "")
        self.assertEqual(result["blurb"], "Body text here.")
        self.assertEqual(result["goal_amount"], "")
        self.assertEqual(result["amount_raised"], "")
        self.assertEqual(result["contributor_count"], "")
        self.assertEqual(result["deadline"], "")

    def test_returns_created_by_name_when_set(self):
        post = MagicMock()
        post.title = "Proposal"
        post.renderable_text = ""
        creator = MagicMock()
        creator.first_name = "Jane"
        creator.last_name = "Doe"
        creator.email = "jane@example.com"
        post.created_by = creator
        post.unified_document = MagicMock()
        post.unified_document.fundraises.first.return_value = None
        post.unified_document.frontend_view_link.return_value = "https://x.com/post/1/s"
        result = build_proposal_context(post)
        self.assertEqual(result["created_by_name"], "Jane Doe")

    def test_resolves_post_via_udoc_get_document(self):
        inner = MagicMock()
        inner.title = "Via UDoc"
        inner.renderable_text = "Blurb"
        inner.created_by = None
        udoc = MagicMock()
        udoc.unified_document = udoc
        udoc.title = None
        udoc.get_document.return_value = inner
        udoc.frontend_view_link.return_value = "https://fund/p"
        udoc.fundraises.first.return_value = None
        result = build_proposal_context(udoc)
        self.assertEqual(result["title"], "Via UDoc")
        self.assertEqual(result["url"], "https://fund/p")

    def test_returns_empty_dict_on_unexpected_error(self):
        post = MagicMock()
        post.title = "OK"
        post.renderable_text = "x"
        post.created_by = None
        post.unified_document = MagicMock()
        post.unified_document.frontend_view_link.return_value = "https://x"
        post.unified_document.fundraises.first.return_value = None
        with patch(
            "ai_expert_finder.services.proposal_email_context._fundraise_email_fields",
            side_effect=RuntimeError("boom"),
        ):
            self.assertEqual(build_proposal_context(post), {})

    def test_description_snippet_length(self):
        post = MagicMock()
        post.title = "T"
        post.renderable_text = "a" * 100
        post.created_by = None
        post.unified_document = MagicMock()
        post.unified_document.fundraises.first.return_value = None
        post.unified_document.frontend_view_link.return_value = "https://x"
        out = build_proposal_context(post, description_snippet_length=10)
        self.assertEqual(out["blurb"], "a" * 10)

    def test_returns_empty_when_no_post_resolved(self):
        udoc = MagicMock()
        udoc.title = None
        udoc.get_document.return_value = None
        self.assertEqual(build_proposal_context(udoc), {})
