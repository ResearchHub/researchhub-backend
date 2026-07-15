"""Unit tests for judge-context compaction (pure functions, no Django)."""

import unittest

from research_ai.services.proposal_tools.judge_context import (
    compact_capabilities,
    compact_profile_context,
)


class CompactCapabilitiesTests(unittest.TestCase):
    def test_keeps_capability_fields_and_drops_empty(self):
        # Arrange
        capabilities = [
            {
                "kind": "technique",
                "name": "cryo-EM",
                "note": "solved a channel structure",
                "evidence": ["https://doi.org/10.1/a"],
            },
            "not a dict",
            {"kind": "dataset", "name": "UK Biobank", "evidence": []},
        ]

        # Act
        out = compact_capabilities(capabilities, max_capabilities=12)

        # Assert: the non-dict is skipped; empty evidence is dropped from the entry.
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["name"], "cryo-EM")
        self.assertNotIn("evidence", out[1])

    def test_caps_the_number_of_capabilities(self):
        # Arrange
        capabilities = [
            {"kind": "technique", "name": f"method-{i}", "evidence": ["u"]}
            for i in range(10)
        ]

        # Act
        out = compact_capabilities(capabilities, max_capabilities=3)

        # Assert
        self.assertEqual(len(out), 3)

    def test_handles_non_list_input(self):
        # Arrange / Act / Assert
        self.assertEqual(compact_capabilities(None, max_capabilities=5), [])


class CompactProfileContextTests(unittest.TestCase):
    def test_includes_capabilities_for_judges(self):
        # Arrange
        profile = {
            "resolution": {"display_name": "Jane Doe", "confidence": 0.9},
            "works": [{"title": "Folding", "source_url": "u"}],
            "capabilities": [
                {"kind": "instrument", "name": "cryo-EM", "evidence": ["u"]}
            ],
        }

        # Act
        out = compact_profile_context(
            profile, max_works=5, max_abstract_chars=200, max_capabilities=12
        )

        # Assert
        self.assertEqual(out["capabilities"][0]["name"], "cryo-EM")

    def test_capabilities_default_empty_when_absent(self):
        # Arrange: an older profile with no capabilities key.
        profile = {"resolution": {}, "works": []}

        # Act
        out = compact_profile_context(profile, max_works=5, max_abstract_chars=200)

        # Assert
        self.assertEqual(out["capabilities"], [])
