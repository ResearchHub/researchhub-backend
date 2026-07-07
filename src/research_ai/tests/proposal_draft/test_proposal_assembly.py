"""Unit tests for the sections -> (plain_text, ProseMirror) assembler (no Django)."""

import unittest

from research_ai.services.proposal_tools.assembly import assemble_proposal


def _full_sections():
    return {
        "title": "A Study of Folding",
        "background": "X drives Y.",
        "preliminary_data": "Pilot data show a trend.",
        "aims": [
            {"title": "Map the trajectory", "body": "First we do A.\n\nThen we do B."},
            {"title": "Test the signal", "body": "We quantify C."},
        ],
        "why_this_team": "Jane has the track record.",
        "budget": "$50,000 across compute and storage.",
        "timeline": "24 months with monthly milestones.",
    }


class AssembleProposalTests(unittest.TestCase):
    def _headings(self, doc, level):
        return [
            n["content"][0]["text"]
            for n in doc["content"]
            if n["type"] == "heading" and n["attrs"]["level"] == level
        ]

    def test_renders_numbered_grant_hierarchy(self):
        # Arrange
        sections = _full_sections()

        # Act
        plain_text, doc = assemble_proposal(sections)

        # Assert: H1 title, numbered H2 top-level sections in order.
        self.assertEqual(doc["type"], "doc")
        self.assertEqual(self._headings(doc, 1), ["A Study of Folding"])
        self.assertEqual(
            self._headings(doc, 2),
            [
                "1. Background and Hypothesis",
                "2. Research Strategy",
                "3. Investigator and Team Qualifications",
                "4. Budget and Timeline",
            ],
        )
        # H3 subsections nest under Research Strategy and Budget and Timeline.
        self.assertEqual(
            self._headings(doc, 3),
            [
                "2.1 Preliminary Data and Rationale",
                "2.2 Specific Aims",
                "4.1 Budget Justification",
                "4.2 Timeline and Milestones",
            ],
        )

    def test_specific_aims_render_as_numbered_titled_subheadings(self):
        # Arrange / Act
        _plain, doc = assemble_proposal(_full_sections())

        # Assert: each aim is an H4 "Specific Aim N: <title>" and its multi-paragraph
        # body becomes one paragraph node per blank-line-separated paragraph.
        self.assertEqual(
            self._headings(doc, 4),
            ["Specific Aim 1: Map the trajectory", "Specific Aim 2: Test the signal"],
        )
        paragraphs = [
            n["content"][0]["text"] for n in doc["content"] if n["type"] == "paragraph"
        ]
        self.assertIn("First we do A.", paragraphs)
        self.assertIn("Then we do B.", paragraphs)

    def test_citations_render_as_numbered_references_section(self):
        # Arrange: two citations, one with a bare DOI, one with a full URL.
        citations = [
            {
                "claim_id": "c1",
                "doi": "10.1/abc",
                "title": "First Paper",
                "authors": ["Ada Lovelace", "Alan Turing"],
            },
            {"claim_id": "c2", "doi": "https://doi.org/10.2/xyz", "title": "Second"},
        ]

        # Act
        plain_text, doc = assemble_proposal(_full_sections(), citations)

        # Assert: a References H2 plus a numbered paragraph per citation, DOIs
        # normalized to resolvable URLs.
        self.assertIn("5. References", self._headings(doc, 2))
        self.assertIn(
            "1. Ada Lovelace, Alan Turing. First Paper. https://doi.org/10.1/abc",
            plain_text,
        )
        self.assertIn("2. Second. https://doi.org/10.2/xyz", plain_text)

    def test_no_citations_yields_no_references_section(self):
        # Arrange / Act
        _plain, doc = assemble_proposal(_full_sections(), [])

        # Assert
        self.assertNotIn("5. References", self._headings(doc, 2))

    def test_empty_sections_yield_empty_doc(self):
        # Arrange / Act: a missing/empty sections object.
        plain_text, doc = assemble_proposal({})

        # Assert: an empty doc and empty text -- the gate's shape/length checks
        # then reject the stub.
        self.assertEqual(plain_text, "")
        self.assertEqual(doc, {"type": "doc", "content": []})

    def test_container_with_all_empty_children_is_skipped(self):
        # Arrange: a title plus only the background section; Research Strategy and
        # Budget and Timeline have no content.
        sections = {"title": "T", "background": "The premise."}

        # Act
        _plain, doc = assemble_proposal(sections)

        # Assert: only the Background H2 renders; empty containers are dropped.
        self.assertEqual(self._headings(doc, 2), ["1. Background and Hypothesis"])
        self.assertEqual(self._headings(doc, 3), [])

    def test_partial_container_renders_only_filled_subsection(self):
        # Arrange: budget present, timeline empty.
        sections = {"title": "T", "budget": "$5,000 total.", "timeline": ""}

        # Act
        _plain, doc = assemble_proposal(sections)

        # Assert: the container renders with only its filled subsection.
        self.assertEqual(self._headings(doc, 2), ["4. Budget and Timeline"])
        self.assertEqual(self._headings(doc, 3), ["4.1 Budget Justification"])

    def test_aim_without_body_is_skipped(self):
        # Arrange: one complete aim and one missing its body.
        sections = {
            "title": "T",
            "aims": [
                {"title": "Complete", "body": "Real prose."},
                {"title": "Incomplete", "body": ""},
            ],
        }

        # Act
        _plain, doc = assemble_proposal(sections)

        # Assert: only the complete aim renders.
        self.assertEqual(
            [
                n["content"][0]["text"]
                for n in doc["content"]
                if n["type"] == "heading" and n["attrs"]["level"] == 4
            ],
            ["Specific Aim 1: Complete"],
        )
