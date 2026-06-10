"""Unit tests for researcher_profile.web_enrichment."""

from django.test import SimpleTestCase

from research_ai.services.researcher_profile import web_enrichment


class WebFindingsParseTests(SimpleTestCase):
    def test_parses_valid_findings_and_drops_unsourced(self):
        # Arrange
        raw = (
            '{"findings": ['
            '{"text": "Runs the Doe Lab", "url": "https://doe-lab.edu"},'
            '{"text": "No source claim", "url": ""},'
            '{"text": "", "url": "https://x.edu"}'
            "]}"
        )
        # Act
        findings = web_enrichment._parse_web_findings(raw)
        # Assert
        self.assertEqual(
            findings, [{"text": "Runs the Doe Lab", "url": "https://doe-lab.edu"}]
        )

    def test_parses_findings_from_code_fence(self):
        # Arrange
        raw = '```json\n{"findings": [{"text": "Talk at NIH", "url": "https://nih.gov/t"}]}\n```'
        # Act
        findings = web_enrichment._parse_web_findings(raw)
        # Assert
        self.assertEqual(
            findings, [{"text": "Talk at NIH", "url": "https://nih.gov/t"}]
        )

    def test_invalid_json_returns_empty(self):
        # Act / Assert
        self.assertEqual(web_enrichment._parse_web_findings("not json at all"), [])
        self.assertEqual(web_enrichment._parse_web_findings(""), [])
