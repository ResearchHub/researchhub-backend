"""Judge panel for the proposal draft loop.

The critique step scores a draft with a roster of one or more judges, reduced by
median (absolute scoring) and majority (pairwise). The default roster is a single
judge on the **generator model itself** -- in practice it critiques its own
drafts harshly enough to surface real issues. Name refs in ``JUDGE_MODEL_IDS``
below for a multi-model, cross-family panel; each roster entry is a model ref
resolved through the provider registry, so an unprefixed id stays on the
generator's provider while a ``bedrock:<id>`` / ``claude_platform:<id>`` ref
routes that one judge elsewhere.

The panel runs two modes off the roster:

- ``score(proposal)`` -- each judge rates the seven rubric criteria 1-5; reduced
  by **median** per criterion, with the **overall** the mean of the seven (a
  float, so a fractional threshold is meaningful). Drives the threshold gate (did
  the draft clear bar). c7 scores the scientific writing voice, so the revise
  loop fixes LLM-tell prose, not just substance.
- ``pairwise(a, b)``  -- each judge picks A vs B; **majority** wins. Drives the
  seed-selection tournament (the more reliable signal).

The panel only produces subjective scores. It never sees or touches the
deterministic programmatic gates -- those stay external to it.
"""

import json
import logging
import statistics

from research_ai.prompts._loader import load_template
from research_ai.services.agent import (
    IncompleteTurnError,
    LLMProvider,
    Message,
    StopReason,
    TextBlock,
    generator_model_ref,
    resolve_provider,
)
from research_ai.services.expert_finder.json_parsing import ExpertFinderJson

logger = logging.getLogger(__name__)

_RUBRIC_CRITERIA = ("c1", "c2", "c3", "c4", "c5", "c6", "c7")
_MIN_SCORE = 1
_MAX_SCORE = 5

# One judge turn's total output budget. Reasoning counts against it (thinking is
# on by default from Opus 5) and the verdict is written *after* the
# deliberation, so a ceiling sized to the verdict alone buys a judge that stops
# mid-JSON -- and a judge that stops mid-JSON reports nothing at all. Sized like
# the generator's own turn budget rather than to the size of a rubric verdict.
JUDGE_MAX_TOKENS = 32768

# Attempts per judge per call. The roster defaults to a single judge, so one
# throttled call or one truncated verdict would otherwise empty the panel --
# and an empty panel ends the whole run, not just the round.
JUDGE_ATTEMPTS = 2

# Stop reasons that mean the turn cannot carry a complete verdict, whatever text
# it managed to emit: the model deliberated through its whole budget, or a
# safety classifier cut the turn short.
_UNUSABLE_STOP_REASONS = (StopReason.MAX_TOKENS, StopReason.CONTENT_FILTERED)

# The judge roster, as model refs. Empty means a single judge on the generator
# model. Name refs here for a multi-model, cross-family panel; an entry may
# carry a provider prefix (``bedrock:`` / ``claude_platform:``) to route that
# judge somewhere other than the generator's provider.
JUDGE_MODEL_IDS: list[str] = []


def _default_generator_id() -> str:
    # The registry's ref carries the provider prefix, so the default
    # single-judge roster lands on the same provider and model the generator
    # uses.
    return generator_model_ref()


def _default_roster_ids(generator_id: str) -> list[str]:
    """The configured roster; defaults to a single judge on the generator."""
    return list(JUDGE_MODEL_IDS) or [generator_id]


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


def _mean_float(values: list[int]) -> float:
    """Mean of 1-5 scores as a float clamped to 1-5 (default 1 when empty).

    The overall uses a mean, not an integer median, so a fractional threshold
    (e.g. 4.5) is a real, partially-achievable target rather than an unreachable
    decimal that collapses to "must score a perfect 5".
    """
    if not values:
        return float(_MIN_SCORE)
    return max(_MIN_SCORE, min(_MAX_SCORE, round(statistics.fmean(values), 2)))


def _render_context(context: dict | None) -> str:
    """Render optional evaluation context for judge prompts."""
    if not context:
        return "No external evaluation context was provided."
    return json.dumps(
        context,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )


def _score_user_prompt(proposal: str, context: dict | None) -> str:
    return (
        "## Evaluation context\n"
        f"{_render_context(context)}\n\n"
        "## Proposal to score\n"
        f"{proposal}"
    )


def _pairwise_user_prompt(a: str, b: str, context: dict | None) -> str:
    return (
        "## Evaluation context\n"
        f"{_render_context(context)}\n\n"
        "## Proposal A\n"
        f"{a}\n\n"
        "## Proposal B\n"
        f"{b}"
    )


class ProposalJudgePanel:
    """A roster of judges (one provider per model ref) scored by median / majority.

    Args:
        providers: Explicit judge providers (one per judge). When omitted, a
            default roster is built lazily from the module roster. Injected in
            tests.
        generator_model_id: The generator's model id; the default roster is a
            single judge on this model.
        max_tokens / temperature: Inference config for each judge call; see
            ``JUDGE_MAX_TOKENS`` for why the budget is sized well past the
            verdict itself.
    """

    def __init__(
        self,
        *,
        providers: list[LLMProvider] | None = None,
        generator_model_id: str | None = None,
        max_tokens: int = JUDGE_MAX_TOKENS,
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
                resolve_provider(model_id) for model_id in self._model_ids
            ]
        return self._providers

    # -- public modes -----------------------------------------------------

    def score(self, proposal: str, *, context: dict | None = None) -> dict:
        """Score ``proposal`` 1-5 on each rubric criterion (median per criterion),
        with the overall the mean of the seven.

        Returns ``{"scores": {c1..c7}, "overall", "gaps": [...],
        "judges_reporting": n, "judge_errors": [...]}``. Judges that fail to
        return parseable JSON are skipped; the gate degrades rather than
        aborting the run. ``judges_reporting`` tells the caller how many judges
        actually scored -- with zero, the 1s in ``scores`` are empty-input
        defaults, not a verdict, and must not be read as one, and
        ``judge_errors`` says what went wrong for each judge that dropped out.
        """
        system_prompt = load_template("proposal_draft_critique.txt")
        user_prompt = _score_user_prompt(proposal, context)
        per_criterion: dict[str, list[int]] = {c: [] for c in _RUBRIC_CRITERIA}
        gaps: list[str] = []
        parsed_results, errors = self._collect(system_prompt, user_prompt)
        for parsed in parsed_results:
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
        overall = _mean_float(list(scores.values()))
        return {
            "scores": scores,
            "overall": overall,
            "gaps": gaps,
            "judges_reporting": len(parsed_results),
            "judge_errors": errors,
        }

    def pairwise(self, a: str, b: str, *, context: dict | None = None) -> str:
        """Each judge picks A vs B; majority wins. Returns ``"A"`` or ``"B"``.

        Ties (including an all-unparseable panel) break to ``"A"`` -- the
        incumbent in the tournament's bracket.
        """
        system_prompt = load_template("proposal_pairwise.txt")
        user_prompt = _pairwise_user_prompt(a, b, context)
        a_votes = 0
        b_votes = 0
        parsed_results, _errors = self._collect(system_prompt, user_prompt)
        for parsed in parsed_results:
            winner = str(parsed.get("winner") or "").strip().upper()
            if winner == "A":
                a_votes += 1
            elif winner == "B":
                b_votes += 1
        return "B" if b_votes > a_votes else "A"

    # -- internals --------------------------------------------------------

    def _collect(
        self, system_prompt: str, user_prompt: str
    ) -> tuple[list[dict], list[str]]:
        """Run every judge; return each one's parsed JSON plus why any dropped out.

        A judge that never reports is skipped rather than aborting the panel,
        and its reason is returned alongside the verdicts: an empty panel ends
        the run, so the cause has to travel with the result instead of living
        only in the logs.
        """
        parsed_results: list[dict] = []
        errors: list[str] = []
        for provider in self._get_providers():
            parsed, error = self._judge(provider, system_prompt, user_prompt)
            if parsed is not None:
                parsed_results.append(parsed)
            else:
                errors.append(f"{getattr(provider, 'model_id', '?')}: {error}")
        if not parsed_results:
            logger.error("judge panel returned no scores: %s", "; ".join(errors))
        return parsed_results, errors

    def _judge(
        self, provider: LLMProvider, system_prompt: str, user_prompt: str
    ) -> tuple[dict | None, str]:
        """One judge's verdict as ``(parsed, "")``, or ``(None, reason)``.

        Retried because the default roster is a single judge: one throttled
        call, one truncated turn, or one non-JSON answer would otherwise empty
        the panel and end the run on a transient failure.
        """
        model_id = getattr(provider, "model_id", "?")
        reason = "no attempt ran"
        for attempt in range(1, JUDGE_ATTEMPTS + 1):
            try:
                parsed = ExpertFinderJson.parse_text(
                    self._complete(provider, system_prompt, user_prompt)
                )
            except Exception as exc:  # noqa: BLE001 - one bad judge must not abort
                reason = str(exc) or type(exc).__name__
            else:
                if isinstance(parsed, dict):
                    return parsed, ""
                # Valid JSON of the wrong shape (a list, a bare string): a
                # skip like any other, but silence here reads as "the judge
                # was never called".
                reason = f"returned JSON {type(parsed).__name__}, not an object"
            logger.warning(
                "judge %r attempt %d/%d failed: %s",
                model_id,
                attempt,
                JUDGE_ATTEMPTS,
                reason,
            )
        return None, reason

    def _complete(
        self, provider: LLMProvider, system_prompt: str, user_prompt: str
    ) -> str:
        """One judge call's verdict text; raises when the turn cannot hold one.

        A turn that ended at its token ceiling or under a content filter has no
        complete JSON in it whatever text it emitted, and an empty turn has
        nothing at all. Both are named by stop reason here so the failure reads
        as what it is rather than as a downstream JSON parse error.
        """
        turn = provider.complete(
            system_prompt=system_prompt,
            messages=[Message(role="user", content=[TextBlock(text=user_prompt)])],
            rendered_tools={},
            max_tokens=self._max_tokens,
            temperature=self._temperature,
        )
        text = turn.text.strip()
        if turn.stop_reason in _UNUSABLE_STOP_REASONS:
            raise IncompleteTurnError(
                f"turn ended {turn.stop_reason} with {len(text)} chars of "
                f"verdict (max_tokens={self._max_tokens})",
                stop_reason=str(turn.stop_reason),
            )
        if not text:
            raise IncompleteTurnError(
                f"turn ended {turn.stop_reason} with no text",
                stop_reason=str(turn.stop_reason),
            )
        return text
