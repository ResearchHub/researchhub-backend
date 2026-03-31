from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from ai_expert_finder.services.expert_search_email_document_context import (
    ExpertSearchEmailDocumentContext,
    _build_generic_linked_document,
    _build_paper_generic,
    _fallback_from_expert_search,
    _nonempty_generic,
    _safe_get_document,
    format_document_context_for_llm,
    resolve_expert_search_email_document_context,
)
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    NOTE,
    PAPER,
    PREREGISTRATION,
)


class FallbackFromExpertSearchTests(SimpleTestCase):
    def test_none_returns_empty_dict(self):
        self.assertEqual(_fallback_from_expert_search(None), {})

    def test_uses_name_and_query_blurb(self):
        es = MagicMock()
        es.name = "Named search"
        es.query = "Full text query for context"
        d = _fallback_from_expert_search(es)
        self.assertEqual(d["title"], "Named search")
        self.assertEqual(d["kind"], "custom_query")
        self.assertEqual(d["url"], "")
        self.assertIn("Full text", d["blurb"])

    def test_query_only_derives_title_and_truncates_long_query(self):
        es = MagicMock()
        es.name = ""
        es.query = "y" * 250
        d = _fallback_from_expert_search(es)
        self.assertTrue(d["title"].endswith("…"))
        self.assertEqual(len(d["title"]), 201)
        self.assertEqual(len(d["blurb"]), 250)

    def test_blurb_truncates_when_query_exceeds_snippet_len(self):
        es = MagicMock()
        es.name = ""
        es.query = "z" * 600
        d = _fallback_from_expert_search(es)
        self.assertEqual(len(d["blurb"]), 500)

    def test_empty_search_returns_empty_title_blurb(self):
        es = MagicMock()
        es.name = ""
        es.query = ""
        d = _fallback_from_expert_search(es)
        self.assertEqual(d["title"], "")
        self.assertEqual(d["blurb"], "")


class NonemptyGenericTests(SimpleTestCase):
    def test_empty_or_no_text_returns_none(self):
        self.assertIsNone(_nonempty_generic({}))
        self.assertIsNone(_nonempty_generic({"title": "", "blurb": ""}))

    def test_title_or_blurb_suffices(self):
        self.assertEqual(
            _nonempty_generic({"title": "x", "blurb": ""}), {"title": "x", "blurb": ""}
        )
        self.assertEqual(
            _nonempty_generic({"title": "", "blurb": "y"}),
            {"title": "", "blurb": "y"},
        )


class SafeGetDocumentTests(SimpleTestCase):
    def test_returns_get_document_result(self):
        udoc = MagicMock()
        inner = object()
        udoc.get_document.return_value = inner
        self.assertIs(_safe_get_document(udoc), inner)

    def test_falls_back_to_posts_first_on_get_document_error(self):
        udoc = MagicMock()
        udoc.id = 99
        udoc.get_document.side_effect = RuntimeError("boom")
        post = MagicMock()
        udoc.posts.first.return_value = post
        self.assertIs(_safe_get_document(udoc), post)

    def test_returns_none_when_both_fail(self):
        udoc = MagicMock()
        udoc.id = 1
        udoc.get_document.side_effect = RuntimeError("boom")
        udoc.posts.first.side_effect = RuntimeError("also boom")
        self.assertIsNone(_safe_get_document(udoc))


class BuildPaperGenericTests(SimpleTestCase):
    def test_no_paper_returns_empty(self):
        udoc = MagicMock()
        udoc.paper = None
        self.assertEqual(_build_paper_generic(udoc), {})

    def test_builds_from_paper_and_link(self):
        udoc = MagicMock()
        paper = MagicMock()
        paper.title = " Paper title "
        paper.abstract = " Abstract body "
        udoc.paper = paper
        udoc.frontend_view_link.return_value = "https://rh/paper/1"
        d = _build_paper_generic(udoc)
        self.assertEqual(d["kind"], "paper")
        self.assertEqual(d["title"], "Paper title")
        self.assertEqual(d["url"], "https://rh/paper/1")
        self.assertIn("Abstract body", d["blurb"])

    def test_frontend_link_failure_still_returns_title(self):
        udoc = MagicMock()
        paper = MagicMock()
        paper.title = "T"
        paper.abstract = ""
        udoc.paper = paper
        udoc.frontend_view_link.side_effect = RuntimeError("link down")
        d = _build_paper_generic(udoc)
        self.assertEqual(d["title"], "T")
        self.assertEqual(d["url"], "")


class BuildGenericLinkedDocumentTests(SimpleTestCase):
    def test_no_inner_doc_returns_empty(self):
        udoc = MagicMock()
        udoc.get_document.return_value = None
        udoc.posts.first.return_value = None
        self.assertEqual(_build_generic_linked_document(udoc), {})

    def test_coerces_non_string_blurb(self):
        udoc = MagicMock()
        doc = MagicMock()
        doc.title = "Post T"
        doc.renderable_text = None
        doc.text = 12345
        udoc.get_document.return_value = doc
        udoc.frontend_view_link.return_value = "https://rh/p/1"
        d = _build_generic_linked_document(udoc)
        self.assertEqual(d["kind"], "generic")
        self.assertEqual(d["title"], "Post T")
        self.assertEqual(d["blurb"], "12345")


def _mock_expert_search_with_udoc(document_type):
    es = MagicMock()
    es.unified_document_id = 1
    udoc = MagicMock()
    udoc.document_type = document_type
    es.unified_document = udoc
    return es, udoc


class ResolveExpertSearchEmailDocumentContextTests(SimpleTestCase):
    def test_none_expert_search(self):
        ctx = resolve_expert_search_email_document_context(None)
        self.assertIsNone(ctx.rfp_context_dict)
        self.assertIsNone(ctx.proposal_context_dict)
        self.assertIsNone(ctx.generic_work_context_dict)

    def test_no_unified_document_uses_fallback(self):
        es = MagicMock()
        es.unified_document_id = None
        es.name = "Q-only"
        es.query = "find experts in ML"
        ctx = resolve_expert_search_email_document_context(es)
        self.assertIsNone(ctx.rfp_context_dict)
        self.assertIsNotNone(ctx.generic_work_context_dict)
        self.assertEqual(ctx.generic_work_context_dict["kind"], "custom_query")

    @patch(
        "ai_expert_finder.services.expert_search_email_document_context.build_rfp_context"
    )
    @patch("ai_expert_finder.services.expert_search_email_document_context.resolve_grant")
    def test_grant_with_rfp_context(self, mock_resolve, mock_build_rfp):
        es, _ = _mock_expert_search_with_udoc(GRANT)
        mock_resolve.return_value = MagicMock()
        mock_build_rfp.return_value = {"title": "RFP X", "blurb": "About the grant"}
        ctx = resolve_expert_search_email_document_context(es)
        self.assertEqual(ctx.rfp_context_dict["title"], "RFP X")
        self.assertIsNone(ctx.proposal_context_dict)
        self.assertIsNone(ctx.generic_work_context_dict)

    @patch(
        "ai_expert_finder.services.expert_search_email_document_context.build_rfp_context"
    )
    @patch("ai_expert_finder.services.expert_search_email_document_context.resolve_grant")
    def test_grant_no_grant_or_empty_rfp_falls_back(self, mock_resolve, mock_build_rfp):
        es, _ = _mock_expert_search_with_udoc(GRANT)
        es.name = "Fallback name"
        es.query = ""
        mock_resolve.return_value = None
        ctx = resolve_expert_search_email_document_context(es)
        self.assertIsNone(ctx.rfp_context_dict)
        self.assertIsNotNone(ctx.generic_work_context_dict)
        self.assertEqual(ctx.generic_work_context_dict["title"], "Fallback name")

    @patch(
        "ai_expert_finder.services.expert_search_email_document_context.build_proposal_context"
    )
    def test_preregistration_with_proposal(self, mock_proposal):
        es, _ = _mock_expert_search_with_udoc(PREREGISTRATION)
        mock_proposal.return_value = {"title": "Prereg T", "blurb": "Hypothesis"}
        ctx = resolve_expert_search_email_document_context(es)
        self.assertIsNone(ctx.rfp_context_dict)
        self.assertEqual(ctx.proposal_context_dict["title"], "Prereg T")
        self.assertIsNone(ctx.generic_work_context_dict)

    @patch(
        "ai_expert_finder.services.expert_search_email_document_context.build_proposal_context"
    )
    def test_preregistration_empty_proposal_falls_back(self, mock_proposal):
        es, _ = _mock_expert_search_with_udoc(PREREGISTRATION)
        es.name = "S"
        es.query = "q"
        mock_proposal.return_value = {}
        ctx = resolve_expert_search_email_document_context(es)
        self.assertIsNone(ctx.proposal_context_dict)
        self.assertIsNotNone(ctx.generic_work_context_dict)

    @patch(
        "ai_expert_finder.services.expert_search_email_document_context._build_paper_generic",
        return_value={"title": "Pap", "blurb": "Abst", "url": "", "kind": "paper"},
    )
    def test_paper_branch(self, _mock_paper):
        es, _ = _mock_expert_search_with_udoc(PAPER)
        ctx = resolve_expert_search_email_document_context(es)
        self.assertEqual(ctx.generic_work_context_dict["kind"], "paper")

    @patch(
        "ai_expert_finder.services.expert_search_email_document_context._build_paper_generic",
        return_value={},
    )
    def test_paper_empty_falls_back(self, _mock_paper):
        es, _ = _mock_expert_search_with_udoc(PAPER)
        es.name = "Paper fallback"
        es.query = ""
        ctx = resolve_expert_search_email_document_context(es)
        self.assertEqual(ctx.generic_work_context_dict["title"], "Paper fallback")

    @patch(
        "ai_expert_finder.services.expert_search_email_document_context._build_generic_linked_document",
        return_value={"title": "Note", "blurb": "Body", "url": "u", "kind": "generic"},
    )
    def test_other_document_type_uses_generic_linked(self, _mock_gen):
        es, _ = _mock_expert_search_with_udoc(NOTE)
        ctx = resolve_expert_search_email_document_context(es)
        self.assertEqual(ctx.generic_work_context_dict["title"], "Note")

    @patch(
        "ai_expert_finder.services.expert_search_email_document_context._build_generic_linked_document",
        return_value={},
    )
    def test_generic_linked_empty_falls_back(self, _mock_gen):
        es, _ = _mock_expert_search_with_udoc(NOTE)
        es.name = "N"
        es.query = "help"
        ctx = resolve_expert_search_email_document_context(es)
        self.assertEqual(ctx.generic_work_context_dict["kind"], "custom_query")


class FormatDocumentContextForLlmTests(SimpleTestCase):
    def test_empty_context(self):
        ctx = ExpertSearchEmailDocumentContext(None, None, None)
        self.assertEqual(format_document_context_for_llm(ctx), "")

    def test_grant_narrative_optional_lines(self):
        ctx = ExpertSearchEmailDocumentContext(
            {
                "title": "G",
                "amount": "$5K",
                "deadline": "Jan 1",
                "blurb": "Desc",
                "url": "https://g",
            },
            None,
            None,
        )
        s = format_document_context_for_llm(ctx)
        self.assertIn("grant or funding opportunity", s)
        self.assertIn("G", s)
        self.assertIn("$5K", s)
        self.assertIn("Jan 1", s)
        self.assertIn("Desc", s)
        self.assertIn("https://g", s)

    def test_proposal_narrative(self):
        ctx = ExpertSearchEmailDocumentContext(
            None,
            {
                "title": "Prop",
                "created_by_name": "Ada",
                "goal_amount": "$10",
                "blurb": "About",
                "url": "https://p",
            },
            None,
        )
        s = format_document_context_for_llm(ctx)
        self.assertIn("preregistration", s)
        self.assertIn("Ada", s)
        self.assertIn("Prop", s)

    def test_generic_paper_lead(self):
        ctx = ExpertSearchEmailDocumentContext(
            None,
            None,
            {"kind": "paper", "title": "T", "blurb": "B"},
        )
        s = format_document_context_for_llm(ctx)
        self.assertIn("research paper", s)
        self.assertIn("Title: T", s)

    def test_generic_custom_query_lead(self):
        ctx = ExpertSearchEmailDocumentContext(
            None,
            None,
            {"kind": "custom_query", "title": "CQ"},
        )
        s = format_document_context_for_llm(ctx)
        self.assertIn("free-text", s)

    def test_generic_linked_doc_lead(self):
        ctx = ExpertSearchEmailDocumentContext(
            None,
            None,
            {"kind": "generic", "title": "X"},
        )
        s = format_document_context_for_llm(ctx)
        self.assertIn("not a grant", s)

    def test_generic_unknown_kind_else_branch(self):
        ctx = ExpertSearchEmailDocumentContext(
            None,
            None,
            {"kind": "hypothesis", "title": "H"},
        )
        s = format_document_context_for_llm(ctx)
        self.assertIn("hypothesis", s)
        self.assertIn("ResearchHub post or document", s)
