"""Unit tests for the proposal seed-prompt builders (pure functions, no Django)."""

import unittest
from types import SimpleNamespace

from research_ai.prompts.proposal_draft_prompts import (
    _MAX_SEED_ABSTRACT_CHARS,
    build_proposal_user_prompt,
)


def _expert(works):
    return SimpleNamespace(full_name="Jane Smith", profile={"works": works})


class BuildProposalUserPromptTests(unittest.TestCase):
    def test_seed_includes_work_abstract(self):
        # Arrange
        expert = _expert(
            [{"title": "Folding", "abstract": "We study how proteins fold."}]
        )

        # Act
        prompt = build_proposal_user_prompt(expert, {"organization": "NSF"})

        # Assert
        self.assertIn("Folding", prompt)
        self.assertIn("Abstract: We study how proteins fold.", prompt)

    def test_long_abstract_is_truncated_in_seed(self):
        # Arrange: an abstract longer than the seed cap.
        long_abstract = "word " * 400
        expert = _expert([{"title": "Big", "abstract": long_abstract}])

        # Act
        prompt = build_proposal_user_prompt(expert, None)

        # Assert: the seed truncates and marks it; full text stays behind the tool.
        self.assertIn("...", prompt)
        abstract_line = next(
            line for line in prompt.splitlines() if "Abstract:" in line
        )
        self.assertLessEqual(len(abstract_line), _MAX_SEED_ABSTRACT_CHARS + 40)

    def test_work_without_abstract_renders_no_abstract_line(self):
        # Arrange
        expert = _expert([{"title": "No Abstract Work"}])

        # Act
        prompt = build_proposal_user_prompt(expert, None)

        # Assert
        self.assertIn("No Abstract Work", prompt)
        self.assertNotIn("Abstract:", prompt)
