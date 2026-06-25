"""Judge panel for the proposal draft loop.

The critique step scores a draft with a roster of one or more judges, reduced by
median (absolute scoring) and majority (pairwise). The default roster is a single
judge on the **generator model itself** (Opus 4.8) -- in practice it critiques
its own drafts harshly enough to surface real issues. The roster is configurable
via ``RESEARCH_AI_JUDGE_MODEL_IDS`` for anyone who wants a multi-model,
cross-family panel; every judge is the same ``BedrockProvider`` pointed at a
different Converse ``modelId``, so no second provider adapter is needed.

The panel runs two modes off the roster:

- ``score(proposal)`` -- each judge rates the six rubric criteria 1-5; reduced by
  **median** per criterion. Drives the threshold gate (did the draft clear bar).
- ``pairwise(a, b)``  -- each judge picks A vs B; **majority** wins. Drives the
  seed-selection tournament (the more reliable signal).

The panel only produces subjective scores. It never sees or touches the
deterministic programmatic gates -- those stay external to it.
"""

import logging
import os
import statistics

from django.conf import settings

from research_ai.services.agent import BedrockProvider, LLMProvider, Message, TextBlock
from research_ai.services.expert_finder_json import ExpertFinderJson

logger = logging.getLogger(__name__)

# Default generator id, mirrored from the agent core's BedrockProvider default;
# the default judge roster is this same model.
_DEFAULT_GENERATOR_MODEL_ID = "us.anthropic.claude-opus-4-8"

_RUBRIC_CRITERIA = ("c1", "c2", "c3", "c4", "c5", "c6")
_MIN_SCORE = 1
_MAX_SCORE = 5

_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")
_prompt_cache: dict[str, str] = {}


def _load_prompt(name: str) -> str:
    if name not in _prompt_cache:
        path = os.path.join(_PROMPTS_DIR, name)
        with open(path, encoding="utf-8") as f:
            _prompt_cache[name] = f.read()
    return _prompt_cache[name]


def _default_generator_id() -> str:
    return getattr(
        settings, "RESEARCH_AI_GENERATOR_MODEL_ID", _DEFAULT_GENERATOR_MODEL_ID
    )


def _default_roster_ids(generator_id: str) -> list[str]:
    """Roster model ids from settings; defaults to a single judge on the generator."""
    ids = list(getattr(settings, "RESEARCH_AI_JUDGE_MODEL_IDS", []) or [])
    return ids or [generator_id]


def _coerce_score(raw: object) -> int:
    """Coerce one criterion value to an int clamped to 1-5 (default 1)."""
    try:
        value = int(round(float(raw)))
    except (TypeError, ValueError):
        return _MIN_SCORE
    return max(_MIN_SCORE, min(_MAX_SCORE, value))


def _median_int(values: list[int]) -> int:
    """Median of 1-5 scores, rounded and clamped to an int (default 1 when empty)."""
    if not values:
        return _MIN_SCORE
    return max(_MIN_SCORE, min(_MAX_SCORE, int(round(statistics.median(values)))))


class ProposalJudgePanel:
    """A roster of Bedrock judges scored by median / majority.

    Args:
        providers: Explicit judge providers (one per judge). When omitted, a
            default roster is built lazily from settings. Injected in tests.
        generator_model_id: The generator's model id; the default roster is a
            single judge on this model.
        max_tokens / temperature: Inference config for each judge call.
    """

    def __init__(
        self,
        *,
        providers: list[LLMProvider] | None = None,
        generator_model_id: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ):
        self._generator_model_id = generator_model_id or _default_generator_id()
        self._max_tokens = max_tokens
        self._temperature = temperature
        if providers is None:
            self._model_ids = _default_roster_ids(self._generator_model_id)
            self._providers: list[LLMProvider] | None = None
        else:
            self._providers = list(providers)
            self._model_ids = [getattr(p, "model_id", "") for p in self._providers]

    @property
    def model_ids(self) -> list[str]:
        """The roster's model ids (resolved without building any clients)."""
        return list(self._model_ids)

    def _get_providers(self) -> list[LLMProvider]:
        if self._providers is None:
            self._providers = [
                BedrockProvider(model_id=model_id) for model_id in self._model_ids
            ]
        return self._providers

    # -- public modes -----------------------------------------------------

    def score(self, proposal: str) -> dict:
        """Score ``proposal`` 1-5 on each rubric criterion, reduced by median.

        Returns ``{"scores": {c1..c6}, "overall", "gaps": [...]}``. Judges that
        fail to return parseable JSON are skipped; the gate degrades rather than
        aborting the run.
        """
        system_prompt = _load_prompt("proposal_draft_critique.txt")
        per_criterion: dict[str, list[int]] = {c: [] for c in _RUBRIC_CRITERIA}
        gaps: list[str] = []
        for parsed in self._collect(system_prompt, proposal):
            raw_scores = parsed.get("scores")
            raw_scores = raw_scores if isinstance(raw_scores, dict) else {}
            for criterion in _RUBRIC_CRITERIA:
                per_criterion[criterion].append(
                    _coerce_score(raw_scores.get(criterion))
                )
            for gap in parsed.get("gaps") or []:
                gap = str(gap).strip()
                if gap and gap not in gaps:
                    gaps.append(gap)

        scores = {c: _median_int(per_criterion[c]) for c in _RUBRIC_CRITERIA}
        overall = _median_int(list(scores.values()))
        return {"scores": scores, "overall": overall, "gaps": gaps}

    def pairwise(self, a: str, b: str) -> str:
        """Each judge picks A vs B; majority wins. Returns ``"A"`` or ``"B"``.

        Ties (including an all-unparseable panel) break to ``"A"`` -- the
        incumbent in the tournament's bracket.
        """
        system_prompt = _load_prompt("proposal_pairwise.txt")
        user_prompt = f"## Proposal A\n{a}\n\n## Proposal B\n{b}"
        a_votes = 0
        b_votes = 0
        for parsed in self._collect(system_prompt, user_prompt):
            winner = str(parsed.get("winner") or "").strip().upper()
            if winner == "A":
                a_votes += 1
            elif winner == "B":
                b_votes += 1
        return "B" if b_votes > a_votes else "A"

    # -- internals --------------------------------------------------------

    def _collect(self, system_prompt: str, user_prompt: str) -> list[dict]:
        """Run every judge and return each one's parsed JSON (skipping failures)."""
        parsed_results: list[dict] = []
        for provider in self._get_providers():
            try:
                text = self._complete(provider, system_prompt, user_prompt)
                parsed = ExpertFinderJson.parse_text(text)
            except Exception as exc:  # noqa: BLE001 - one bad judge must not abort
                model_id = getattr(provider, "model_id", "?")
                logger.warning("judge %r failed: %s", model_id, exc)
                continue
            if isinstance(parsed, dict):
                parsed_results.append(parsed)
        return parsed_results

    def _complete(
        self, provider: LLMProvider, system_prompt: str, user_prompt: str
    ) -> str:
        turn = provider.complete(
            system_prompt=system_prompt,
            messages=[Message(role="user", content=[TextBlock(text=user_prompt)])],
            rendered_tools={},
            max_tokens=self._max_tokens,
            temperature=self._temperature,
        )
        return turn.text
