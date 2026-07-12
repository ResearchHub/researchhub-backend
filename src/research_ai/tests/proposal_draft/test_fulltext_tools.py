"""Unit tests for the proposal full-text tool (no Django, no network)."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from research_ai.services.proposal_tools.fulltext_tools import (
    ProposalFulltextToolset,
    _doi_from_source_url,
)

_PATCH_BASE = "research_ai.services.proposal_tools.fulltext_tools"


def _search_expert(works):
    """Minimal stand-in: the toolset only reads ``expert.profile``."""
    return SimpleNamespace(expert=SimpleNamespace(profile={"works": works}))


class DoiFromSourceUrlTests(unittest.TestCase):
    def test_strips_known_doi_prefixes(self):
        # Arrange / Act / Assert
        cases = {
            "https://doi.org/10.1/ABC": "10.1/abc",
            "http://doi.org/10.2/x": "10.2/x",  # NOSONAR - test input, not a request
            "https://dx.doi.org/10.3/y": "10.3/y",
            "doi:10.4/z": "10.4/z",
            "10.5/bare": "10.5/bare",
        }
        for source_url, expected in cases.items():
            with self.subTest(source_url=source_url):
                self.assertEqual(_doi_from_source_url(source_url), expected)

    def test_non_doi_urls_return_empty(self):
        # Arrange / Act / Assert: an OpenAlex work URL is not a DOI.
        self.assertEqual(_doi_from_source_url("https://openalex.org/W1"), "")
        self.assertEqual(_doi_from_source_url(""), "")


class GetWorkFulltextTests(unittest.TestCase):
    def setUp(self):
        # pdf_url is empty by default so no test hits the network via the OA
        # fallback; the OpenAlex-PDF test sets it explicitly.
        self.work = {
            "title": "Folding",
            "source_url": "https://doi.org/10.1/a",
            "pdf_url": "",
            "abstract": "Profile abstract for folding.",
        }

    def _toolset(self, *, paper_lookup=None, max_fetches=5):
        return ProposalFulltextToolset(
            _search_expert([self.work]),
            max_fetches=max_fetches,
            paper_lookup=paper_lookup or (lambda doi: None),
        )

    def test_missing_source_url_errors(self):
        # Arrange
        tool = self._toolset().build_tools()[0]

        # Act
        result = tool.handler({})

        # Assert
        self.assertIn("error", result)

    def test_unknown_source_url_errors_without_spending_budget(self):
        # Arrange
        toolset = self._toolset(max_fetches=1)
        handler = toolset.build_tools()[0].handler

        # Act: an unknown url errors and must not consume the read budget...
        miss = handler({"source_url": "https://doi.org/10.9/unknown"})
        hit = handler({"source_url": self.work["source_url"]})

        # Assert
        self.assertIn("error", miss)
        self.assertNotIn("error", hit)

    @patch(f"{_PATCH_BASE}.extract_text_from_pdf_bytes", return_value="LOCAL PDF TEXT")
    @patch(f"{_PATCH_BASE}.get_paper_pdf_bytes", return_value=b"%PDF-bytes")
    def test_prefers_researchhub_paper_pdf(self, _bytes, _extract):
        # Arrange: a local Paper exists for the DOI.
        paper = SimpleNamespace(id=7, abstract="rh abstract")
        toolset = self._toolset(paper_lookup=lambda doi: paper)

        # Act
        result = toolset.build_tools()[0].handler(
            {"source_url": self.work["source_url"]}
        )

        # Assert
        self.assertEqual(result["content_type"], "researchhub_pdf")
        self.assertEqual(result["text"], "LOCAL PDF TEXT")

    @patch(f"{_PATCH_BASE}.get_paper_pdf_bytes", return_value=None)
    def test_falls_back_to_researchhub_abstract_when_no_pdf(self, _bytes):
        # Arrange: local Paper found but its PDF is unavailable.
        paper = SimpleNamespace(id=7, abstract="ResearchHub stored abstract.")
        toolset = self._toolset(paper_lookup=lambda doi: paper)

        # Act
        result = toolset.build_tools()[0].handler(
            {"source_url": self.work["source_url"]}
        )

        # Assert
        self.assertEqual(result["content_type"], "researchhub_abstract")
        self.assertEqual(result["text"], "ResearchHub stored abstract.")

    @patch(f"{_PATCH_BASE}.extract_text_from_pdf_bytes", return_value="OA PDF TEXT")
    @patch(f"{_PATCH_BASE}.get_paper_pdf_bytes", return_value=b"%PDF-bytes")
    def test_falls_back_to_openalex_pdf_when_no_local_paper(self, _bytes, _extract):
        # Arrange: no local Paper, but the work carries an OA pdf_url.
        self.work["pdf_url"] = "https://example.edu/a.pdf"
        toolset = self._toolset(paper_lookup=lambda doi: None)

        # Act
        result = toolset.build_tools()[0].handler(
            {"source_url": self.work["source_url"]}
        )

        # Assert
        self.assertEqual(result["content_type"], "openalex_pdf")
        self.assertEqual(result["text"], "OA PDF TEXT")

    def test_falls_back_to_profile_abstract_when_no_pdf_anywhere(self):
        # Arrange: no local Paper and no readable PDF (empty pdf_url).
        self.work["pdf_url"] = ""
        toolset = self._toolset(paper_lookup=lambda doi: None)

        # Act
        result = toolset.build_tools()[0].handler(
            {"source_url": self.work["source_url"]}
        )

        # Assert
        self.assertEqual(result["content_type"], "profile_abstract")
        self.assertEqual(result["text"], "Profile abstract for folding.")

    def test_read_budget_is_enforced_per_run(self):
        # Arrange: budget of one read; the work resolves to its profile abstract.
        self.work["pdf_url"] = ""
        toolset = self._toolset(paper_lookup=lambda doi: None, max_fetches=1)
        handler = toolset.build_tools()[0].handler

        # Act
        first = handler({"source_url": self.work["source_url"]})
        second = handler({"source_url": self.work["source_url"]})

        # Assert
        self.assertEqual(first["content_type"], "profile_abstract")
        self.assertIn("error", second)
        self.assertIn("budget", second["error"].lower())
