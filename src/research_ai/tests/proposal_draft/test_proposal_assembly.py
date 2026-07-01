"""Unit tests for the sections -> (plain_text, ProseMirror) assembler (no Django)."""

import unittest

from research_ai.services.proposal_tools.assembly import assemble_proposal


class AssembleProposalTests(unittest.TestCase):
    def test_assembles_title_headings_and_paragraphs(self):
        # Arrange: sections with a multi-paragraph body (blank-line separated).
        sections = {
            "title": "A Study of Folding",
            "hypothesis": "X drives Y.",
            "approach": "First we do A.\n\nThen we do B.",
            "why_this_team": "Jane has the track record.",
            "scope_timeline": "24 months, $50,000.",
        }

        # Act
        plain_text, doc = assemble_proposal(sections)

        # Assert: H1 title, an H2 per section, and a paragraph node per paragraph.
        self.assertEqual(doc["type"], "doc")
        headings = [n for n in doc["content"] if n["type"] == "heading"]
        self.assertEqual(headings[0]["attrs"]["level"], 1)
        self.assertEqual(headings[0]["content"][0]["text"], "A Study of Folding")
        h2_texts = [
            h["content"][0]["text"] for h in headings if h["attrs"]["level"] == 2
        ]
        self.assertEqual(
            h2_texts, ["Hypothesis", "Approach", "Why this team", "Scope & timeline"]
        )
        # The two-paragraph approach body becomes two paragraph nodes.
        paragraphs = [
            n["content"][0]["text"] for n in doc["content"] if n["type"] == "paragraph"
        ]
        self.assertIn("First we do A.", paragraphs)
        self.assertIn("Then we do B.", paragraphs)
        # plain_text carries the title and every paragraph's prose.
        self.assertIn("A Study of Folding", plain_text)
        self.assertIn("First we do A.", plain_text)
        self.assertIn("Then we do B.", plain_text)

    def test_empty_sections_yield_empty_doc(self):
        # Arrange / Act: a missing/empty sections object.
        plain_text, doc = assemble_proposal({})

        # Assert: an empty doc and empty text -- the gate's shape/length checks
        # then reject the stub.
        self.assertEqual(plain_text, "")
        self.assertEqual(doc, {"type": "doc", "content": []})

    def test_skips_empty_sections_only(self):
        # Arrange: only a title and one body section are filled.
        sections = {"title": "T", "approach": "Do the thing.", "hypothesis": ""}

        # Act
        _plain, doc = assemble_proposal(sections)

        # Assert: the empty hypothesis is skipped; only title H1 + Approach H2.
        h2_texts = [
            n["content"][0]["text"]
            for n in doc["content"]
            if n["type"] == "heading" and n["attrs"]["level"] == 2
        ]
        self.assertEqual(h2_texts, ["Approach"])
