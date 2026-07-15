"""Unit tests for the proposal seed-prompt builders (pure functions, no Django)."""

import unittest
from types import SimpleNamespace

from research_ai.prompts.proposal_draft_prompts import (
    _MAX_SEED_ABSTRACT_CHARS,
    build_proposal_system_prompt,
    build_proposal_user_prompt,
)


def _expert(works, capabilities=None):
    profile = {"works": works}
    if capabilities is not None:
        profile["capabilities"] = capabilities
    return SimpleNamespace(full_name="Jane Smith", profile=profile)


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

    def test_seed_lists_lab_capabilities(self):
        # Arrange: a profile with a demonstrated capability.
        expert = _expert(
            [{"title": "Folding"}],
            capabilities=[
                {
                    "kind": "technique",
                    "name": "cryo-EM",
                    "note": "solved a channel structure",
                    "evidence": ["https://doi.org/10.1/a"],
                }
            ],
        )

        # Act
        prompt = build_proposal_user_prompt(expert, None)

        # Assert: the capability and its kind seed the draft's bounds.
        self.assertIn("Demonstrated lab capabilities", prompt)
        self.assertIn("cryo-EM", prompt)
        self.assertIn("[technique]", prompt)

    def test_seed_omits_capability_block_when_none(self):
        # Arrange: no capabilities on the profile.
        expert = _expert([{"title": "Folding"}])

        # Act
        prompt = build_proposal_user_prompt(expert, None)

        # Assert
        self.assertNotIn("Demonstrated lab capabilities", prompt)


class BuildProposalSystemPromptTests(unittest.TestCase):
    def test_award_sizes_the_aim_guidance_and_replaces_placeholder(self):
        # Arrange / Act: a small USD award.
        prompt = build_proposal_system_prompt(
            panel_threshold=4.0, award={"amount": "5000", "currency": "USD"}
        )

        # Assert: the concrete cap is stated and no template placeholder leaks.
        self.assertIn("$5,000", prompt)
        self.assertIn("one specific aim", prompt)
        self.assertNotIn("{{AIM_GUIDANCE}}", prompt)
        self.assertNotIn("{{PANEL_THRESHOLD}}", prompt)

    def test_missing_award_falls_back_to_general_rule(self):
        # Arrange / Act: no award supplied.
        prompt = build_proposal_system_prompt()

        # Assert: the general aim rule appears, placeholder still replaced.
        self.assertIn("Size the number of specific aims", prompt)
        self.assertNotIn("{{AIM_GUIDANCE}}", prompt)

    def test_word_bounds_are_substituted_from_the_gate_config(self):
        # Arrange / Act: the length-gate bounds the runner passes in.
        prompt = build_proposal_system_prompt(min_words=300, max_words=2500)

        # Assert: the prompt states the same bounds the gate enforces, and no
        # template placeholder leaks.
        self.assertIn("under 300 or over 2500", prompt)
        self.assertNotIn("{{MIN_WORDS}}", prompt)
        self.assertNotIn("{{MAX_WORDS}}", prompt)

    def test_style_bar_is_substituted_from_the_gate_config(self):
        # Arrange / Act
        prompt = build_proposal_system_prompt(style_threshold=4.5)

        # Assert: scientific voice has an independent quality floor and no
        # template placeholder leaks into the agent prompt.
        self.assertIn("score at least 4.5 on c7", prompt)
        self.assertNotIn("{{STYLE_THRESHOLD}}", prompt)

    def test_prompt_requires_positive_voice_grounding_and_local_edits(self):
        # Arrange / Act
        prompt = build_proposal_system_prompt()

        # Assert: the agent learns from real writing samples and does not use a
        # whole-section rewrite as its default style-fixing strategy.
        self.assertIn("working voice card", prompt)
        self.assertIn("get_work_fulltext", prompt)
        self.assertIn("smallest sufficient edits", prompt)
        self.assertIn("rewrite an entire", prompt)

    def test_prompt_uses_scientific_register_instead_of_proposal_narration(self):
        # Arrange / Act
        prompt = build_proposal_system_prompt()
        normalized = " ".join(prompt.split())

        # Assert: methods lead with purpose, completed work uses past tense, and
        # unsupported status labels are excluded from the qualifications case.
        self.assertIn("make the method, analysis, or", normalized)
        self.assertIn('instead of repeating "I will."', normalized)
        self.assertIn("completed preliminary work", normalized)
        self.assertIn('"junior', normalized)
        self.assertIn("Do not invent titles, bibliometrics, or honors", normalized)

    def test_prompt_requires_limitations_pitfalls_and_alternatives(self):
        # Arrange / Act
        prompt = build_proposal_system_prompt()
        normalized = " ".join(prompt.split())

        # Assert
        self.assertIn("Treat limitations and pitfalls as different", normalized)
        self.assertIn("resulting boundary", normalized)
        self.assertIn("concrete alternative approach", normalized)
        self.assertIn("`limitations`", normalized)
