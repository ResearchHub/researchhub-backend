"""Settings-backed knobs for the proposal-drafting run.

Every field is overridable via a ``RESEARCH_AI_PROPOSAL_*`` setting; the
defaults here are the production baseline. ``from_settings`` reads Django
settings at call time (not import time), so per-test ``override_settings``
takes effect on each run.
"""

from dataclasses import dataclass

from django.conf import settings

# field name -> the Django setting that overrides it.
_SETTING_OVERRIDES = {
    "max_rounds": "RESEARCH_AI_PROPOSAL_MAX_ROUNDS",
    "panel_threshold": "RESEARCH_AI_PROPOSAL_PANEL_THRESHOLD",
    "plateau_patience": "RESEARCH_AI_PROPOSAL_PLATEAU_PATIENCE",
    "max_iterations": "RESEARCH_AI_PROPOSAL_MAX_ITERATIONS",
    "max_tokens": "RESEARCH_AI_PROPOSAL_MAX_TOKENS",
    "temperature": "RESEARCH_AI_PROPOSAL_TEMPERATURE",
    "min_words": "RESEARCH_AI_PROPOSAL_MIN_WORDS",
    "max_words": "RESEARCH_AI_PROPOSAL_MAX_WORDS",
    "max_judge_rfp_chars": "RESEARCH_AI_PROPOSAL_JUDGE_RFP_CHARS",
    "max_judge_works": "RESEARCH_AI_PROPOSAL_JUDGE_WORKS",
    "max_judge_abstract_chars": "RESEARCH_AI_PROPOSAL_JUDGE_ABSTRACT_CHARS",
}


@dataclass(frozen=True)
class ProposalDraftConfig:
    """Knobs for one bounded proposal-drafting run."""

    # Bounded loop: ``max_rounds`` bounds submit attempts (one round = one
    # submit + gate pass); ``max_iterations`` is a looser ceiling on total tool
    # turns so several tool calls can precede each submit. It is sized so
    # ``max_rounds`` (not the iteration cap) is the real limiter: front-loaded
    # research turns plus ~8 revise/judge/verify rounds need well over the old
    # 40, which strangled runs mid-revision (e.g. quitting at round 3 of 8).
    max_rounds: int = 8
    max_iterations: int = 100

    panel_threshold: float = 4.5
    # Stop revising early once the panel is the blocker and its overall has not
    # improved for this many consecutive rounds: a deterministic single-judge
    # panel returns a near-constant score for a near-constant draft, so
    # grinding the round (and iteration) budget against a flat score below the
    # bar buys nothing.
    plateau_patience: int = 3

    max_tokens: int = 16384
    temperature: float = 1.0

    # Length bounds on the readable proposal (words). Wide on purpose: the gate
    # catches an empty/stub draft or a runaway, not stylistic length.
    min_words: int = 250
    max_words: int = 4000

    # Caps on the judge-facing context bundle.
    max_judge_rfp_chars: int = 6000
    max_judge_works: int = 8
    max_judge_abstract_chars: int = 1200

    @classmethod
    def from_settings(cls) -> "ProposalDraftConfig":
        defaults = cls()
        return cls(
            **{
                field: getattr(settings, setting, getattr(defaults, field))
                for field, setting in _SETTING_OVERRIDES.items()
            }
        )
