"""Deterministic gates the submitted draft must clear before the loop may stop.

The gates enforce the driver's "never trust the model's own done signal" rule:
required sections present, length in bounds, every citation grounded in a tool
result and verified against OpenAlex, the scope committed to concrete numbers,
and the judge panel over the bar. ``ProposalGateRunner`` performs no
persistence -- it reports step transitions through an optional callback and
returns ``(accepted, report)``; the runner owns what happens next.
"""

import re
from collections.abc import Callable

from research_ai.models import ProposalDraft
from research_ai.services.proposal_draft.config import ProposalDraftConfig
from research_ai.services.proposal_draft.scope import format_award, max_aims_for_budget
from research_ai.services.proposal_tools import (
    ProposalVerificationToolset,
    assemble_proposal,
    valid_aims,
)
from research_ai.services.proposal_tools.doi import strip_doi_prefix

# The gates in the order they run; also the report keys their results live
# under (``ProposalGateRunner.run`` builds the report from this order).
GATE_NAMES = ("sections", "length", "citations", "scope", "panel")


def failing_gates(report: dict) -> list[str]:
    """Names of the gates ``report`` shows as failed (a missing gate passes)."""
    return [name for name in GATE_NAMES if not (report.get(name) or {}).get("ok", True)]


# Text sections the proposal must carry (keys on the submitted ``sections``
# object). ``aims`` is a list and is checked separately in ``_gate_sections``.
_REQUIRED_SECTIONS = (
    ("title", "title"),
    ("background", "background & hypothesis"),
    ("preliminary_data", "preliminary data & rationale"),
    ("limitations", "limitations, pitfalls & alternative approaches"),
    ("why_this_team", "investigator & team qualifications"),
    ("budget", "budget justification"),
    ("timeline", "timeline & milestones"),
)


def _provenance_keys(urls) -> set[str]:
    """Comparable keys for a set of provenance URLs (raw + DOI-normalized)."""
    keys: set[str] = set()
    for url in urls:
        raw = str(url or "").strip().lower()
        if not raw:
            continue
        keys.add(raw)
        keys.add(strip_doi_prefix(raw))
    return {k for k in keys if k}


def _citation_keys(citation: dict) -> set[str]:
    """Comparable keys a citation could ground against."""
    keys: set[str] = set()
    for value in (citation.get("doi"), citation.get("source_url")):
        raw = str(value or "").strip().lower()
        if raw:
            keys.add(raw)
            keys.add(strip_doi_prefix(raw))
    return {k for k in keys if k}


def _apply_corrections(citations: list[dict], results_by_id: dict) -> list[str]:
    """Adopt the verifier's minor_drift corrections; return the corrected ids.

    The DOI resolved to the same paper but the claimed title/authors drifted,
    so the resolved record -- not the model's typing -- is what the References
    render. The citation dicts are the submitted ones, so this corrects the
    draft in place.
    """
    corrected: list[str] = []
    for c in citations:
        correction = (results_by_id.get(c.get("claim_id")) or {}).get("correction")
        if not correction:
            continue
        c["title"] = correction["title"]
        c["authors"] = correction["authors"]
        if correction.get("year"):
            c["year"] = correction["year"]
        corrected.append(str(c.get("claim_id") or "?"))
    return corrected


def _ungrounded_citations(
    citations: list[dict], provenance_keys: set[str], results_by_id: dict
) -> list[str]:
    """Claim ids of citations no tool result grounds.

    A citation is grounded if it was retrieved (its DOI/URL is in the
    provenance the OpenAlex/profile tools recorded) OR if verify_citations
    resolved its DOI against OpenAlex ground truth to a matching record
    (exact / minor_drift). The second path lets the agent cite a real,
    verified field-level paper outside the researcher's own works without
    re-fetching it through the author tools just to satisfy provenance --
    fabrication is still caught separately (dead / major_fabrication).
    """
    ungrounded: list[str] = []
    for c in citations:
        if _citation_keys(c) & provenance_keys:
            continue
        result = results_by_id.get(c.get("claim_id"))
        if result and result.get("severity") in ("exact", "minor_drift"):
            continue
        ungrounded.append(str(c.get("claim_id") or "?"))
    return ungrounded


def _prosemirror_ok(doc) -> bool:
    """Minimal ProseMirror shape check: a doc node with non-empty content."""
    return (
        isinstance(doc, dict)
        and doc.get("type") == "doc"
        and isinstance(doc.get("content"), list)
        and len(doc["content"]) > 0
    )


class ProposalGateRunner:
    """Runs every deterministic gate over one submitted draft.

    ``judge_context`` supplies the evidence bundle for the panel gate,
    ``grounded_urls`` the provenance set citations must ground against,
    ``award_context`` the RFP terms the scope gate sizes the aim count against,
    and ``on_step`` (optional) receives ``ProposalDraft.Step`` transitions as the
    gates progress -- the runner wires it to progress persistence.
    """

    def __init__(
        self,
        *,
        config: ProposalDraftConfig,
        panel,
        verification_toolset: ProposalVerificationToolset,
        judge_context: Callable[[dict], dict],
        grounded_urls: Callable[[], set[str]],
        award_context: Callable[[], dict] | None = None,
        on_step: Callable[[str], None] | None = None,
    ):
        self.config = config
        self.panel = panel
        self.verification_toolset = verification_toolset
        self.judge_context = judge_context
        self.grounded_urls = grounded_urls
        self.award_context = award_context or dict
        self.on_step = on_step or (lambda step: None)

    def run(self, submitted: dict, *, round_number: int) -> tuple[bool, dict]:
        """Run every deterministic gate; return ``(accepted, report)``.

        ``minor_drift`` citations are corrected in place from their resolved
        records, and the assembled ``plain_text``/``prosemirror`` re-derived,
        so the rendered References -- and what the length gate, panel, and any
        later persistence see -- carry the ground-truth metadata.
        """
        self.on_step(ProposalDraft.Step.VERIFYING)
        sections = submitted.get("sections")
        sections = sections if isinstance(sections, dict) else {}

        sections_check = self._gate_sections(sections, submitted)
        citations_check = self._gate_citations(submitted)
        if citations_check["corrected"]:
            plain_text, prosemirror = assemble_proposal(
                submitted.get("sections"), submitted.get("citations")
            )
            submitted["plain_text"] = plain_text
            submitted["prosemirror"] = prosemirror

        checks = {
            "sections": sections_check,
            "length": self._gate_length(submitted),
            "citations": citations_check,
            "scope": self._gate_scope(sections),
        }
        self.on_step(ProposalDraft.Step.JUDGING)
        checks["panel"] = self._gate_panel(submitted)

        gaps = [
            gap
            for name in GATE_NAMES
            if not checks[name]["ok"]
            for gap in checks[name].get("gaps", [])
        ]

        accepted = not gaps
        report = {
            "accepted": accepted,
            "round": round_number,
            "rounds_used": round_number,
            **checks,
            "gaps": gaps,
        }
        return accepted, report

    # -- individual gates -------------------------------------------------

    def _gate_sections(self, sections: dict, submitted: dict) -> dict:
        missing = [
            label
            for key, label in _REQUIRED_SECTIONS
            if not str(sections.get(key) or "").strip()
        ]
        # ``aims`` is a list of {title, body}; require at least one complete aim.
        if not valid_aims(sections.get("aims")):
            missing.append("specific aims")
        prosemirror_ok = _prosemirror_ok(submitted.get("prosemirror"))
        gaps = [f"Add a non-empty '{label}' section." for label in missing]
        if not prosemirror_ok:
            gaps.append(
                'Provide a valid ProseMirror document ({"type": "doc", '
                '"content": [...]}) with a heading per required section.'
            )
        return {
            "ok": not missing and prosemirror_ok,
            "missing": missing,
            "prosemirror_ok": prosemirror_ok,
            "gaps": gaps,
        }

    def _gate_length(self, submitted: dict) -> dict:
        words = len(str(submitted.get("plain_text") or "").split())
        ok = self.config.min_words <= words <= self.config.max_words
        gaps = []
        if words < self.config.min_words:
            gaps.append(
                f"The proposal is too short ({words} words); expand it past "
                f"{self.config.min_words} words of real content."
            )
        elif words > self.config.max_words:
            gaps.append(
                f"The proposal is too long ({words} words); tighten it under "
                f"{self.config.max_words} words."
            )
        return {
            "ok": ok,
            "words": words,
            "min": self.config.min_words,
            "max": self.config.max_words,
            "gaps": gaps,
        }

    def _gate_citations(self, submitted: dict) -> dict:
        citations = [
            c for c in (submitted.get("citations") or []) if isinstance(c, dict)
        ]
        provenance_keys = _provenance_keys(self.grounded_urls())
        verification = self.verification_toolset.verify_citations(
            {"citations": citations}
        )
        summary = verification.get("summary", {})
        results_by_id = {r.get("claim_id"): r for r in verification.get("results", [])}

        corrected = _apply_corrections(citations, results_by_id)
        ungrounded = _ungrounded_citations(citations, provenance_keys, results_by_id)

        failures = [
            r.get("claim_id")
            for r in verification.get("results", [])
            if r.get("severity") in ("dead", "major_fabrication")
        ]

        gaps: list[str] = []
        if ungrounded:
            gaps.append(
                "These citations are not grounded in any tool result -- cite a "
                "retrieved work, verify the DOI with verify_citations, or remove "
                f"them: {', '.join(ungrounded)}."
            )
        if failures:
            gaps.append(
                "These citations failed verification (dead DOI or fabricated "
                f"metadata): {', '.join(str(f) for f in failures)}."
            )
        ok = not ungrounded and not failures
        return {
            "ok": ok,
            "ungrounded": ungrounded,
            "failures": failures,
            "corrected": corrected,
            "summary": summary,
            "gaps": gaps,
        }

    def _gate_scope(self, sections: dict) -> dict:
        """Light, honest scope check.

        We cannot deterministically judge whether a plan fits a budget -- the
        panel's c2 does that -- but we can require the budget and timeline
        sections to commit to concrete numbers (a duration or dollar figure)
        and cap the number of specific aims to what the award size funds: a
        reviewer flagged a three-aim draft as far too heavy for a small grant,
        so an over-scoped draft (more aims than the award supports) fails here.
        """
        text = f"{sections.get('budget') or ''} {sections.get('timeline') or ''}"
        has_number = bool(re.search(r"\d", text))
        gaps = []
        if not has_number:
            gaps.append(
                "State the budget and timeline concretely (dollar amount and "
                "duration) in the budget and timeline sections."
            )

        award = self.award_context() or {}
        max_aims = max_aims_for_budget(award.get("amount"), award.get("currency"))
        aim_count = len(valid_aims(sections.get("aims")))
        over_scoped = max_aims is not None and aim_count > max_aims
        if over_scoped:
            aim_word = "specific aim" if max_aims == 1 else "specific aims"
            award_text = format_award(award.get("amount"), award.get("currency"))
            gaps.append(
                f"This award ({award_text}) "
                f"funds at most {max_aims} {aim_word}, but the draft has "
                f"{aim_count}. Consolidate to {max_aims} and deepen the work "
                "rather than spreading it across more aims."
            )
        return {
            "ok": has_number and not over_scoped,
            "has_number": has_number,
            "max_aims": max_aims,
            "aims": aim_count,
            "gaps": gaps,
        }

    def _gate_panel(self, submitted: dict) -> dict:
        proposal_text = str(submitted.get("plain_text") or "")
        rollup = self.panel.score(
            proposal_text,
            context=self.judge_context(submitted),
        )
        if rollup.get("judges_reporting") == 0:
            # No judge returned a score: an infrastructure failure, not a
            # quality verdict. Do not present the rollup's empty-input default
            # scores as an evaluation -- ``overall: None`` also keeps the
            # runner's plateau tracker from counting this round.
            return {
                "ok": False,
                "unavailable": True,
                "overall": None,
                "scores": None,
                "threshold": self.config.panel_threshold,
                "rollup": rollup,
                "gaps": ["The judge panel returned no scores (judge failure)."],
            }
        overall = rollup.get("overall", 0)
        scores = rollup.get("scores")
        scores = scores if isinstance(scores, dict) else {}
        style_score = scores.get("c7", 0)
        overall_ok = overall >= self.config.panel_threshold
        style_ok = (
            isinstance(style_score, (int, float))
            and style_score >= self.config.style_threshold
        )
        ok = overall_ok and style_ok
        gaps = []
        if not overall_ok:
            gaps.append(
                f"The judge panel scored this {overall} overall, below the "
                f"{self.config.panel_threshold} bar. Close these gaps: "
                + "; ".join(rollup.get("gaps", []) or ["raise overall quality"])
                + "."
            )
        if not style_ok:
            style_gaps = [
                str(gap)
                for gap in rollup.get("gaps", []) or []
                if str(gap).lower().startswith("c7:")
            ]
            detail = (
                " Close these style gaps: " + "; ".join(style_gaps) + "."
                if style_gaps
                else " Revise the exact spans that read as generic model prose."
            )
            gaps.append(
                f"Scientific writing voice scored {style_score}, below the "
                f"{self.config.style_threshold} c7 bar.{detail}"
            )
        return {
            "ok": ok,
            "overall": overall,
            "scores": scores,
            "threshold": self.config.panel_threshold,
            "style_score": style_score,
            "style_threshold": self.config.style_threshold,
            "style_ok": style_ok,
            "rollup": rollup,
            "gaps": gaps,
        }
