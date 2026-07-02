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
from research_ai.services.proposal_tools import ProposalVerificationToolset
from research_ai.services.proposal_tools.doi import strip_doi_prefix

# Sections the proposal must carry (keys on the submitted ``sections`` object).
_REQUIRED_SECTIONS = (
    ("title", "title"),
    ("hypothesis", "hypothesis / aim"),
    ("approach", "approach / methods"),
    ("why_this_team", "why this team"),
    ("scope_timeline", "scope & timeline"),
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
    ``grounded_urls`` the provenance set citations must ground against, and
    ``on_step`` (optional) receives ``ProposalDraft.Step`` transitions as the
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
        on_step: Callable[[str], None] | None = None,
    ):
        self.config = config
        self.panel = panel
        self.verification_toolset = verification_toolset
        self.judge_context = judge_context
        self.grounded_urls = grounded_urls
        self.on_step = on_step or (lambda step: None)

    def run(self, submitted: dict, *, round_number: int) -> tuple[bool, dict]:
        """Run every deterministic gate; return ``(accepted, report)``."""
        self.on_step(ProposalDraft.Step.VERIFYING)
        sections = submitted.get("sections")
        sections = sections if isinstance(sections, dict) else {}
        gaps: list[str] = []

        section_check = self._gate_sections(sections, submitted)
        length_check = self._gate_length(submitted)
        citation_check = self._gate_citations(submitted)
        scope_check = self._gate_scope(sections)

        self.on_step(ProposalDraft.Step.JUDGING)
        panel_check = self._gate_panel(submitted)

        for check in (
            section_check,
            length_check,
            citation_check,
            scope_check,
            panel_check,
        ):
            if not check["ok"]:
                gaps.extend(check.get("gaps", []))

        accepted = not gaps
        report = {
            "accepted": accepted,
            "round": round_number,
            "rounds_used": round_number,
            "sections": section_check,
            "length": length_check,
            "citations": citation_check,
            "scope": scope_check,
            "panel": panel_check,
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

        ungrounded = [
            str(c.get("claim_id") or "?")
            for c in citations
            if not (_citation_keys(c) & provenance_keys)
        ]
        verification = self.verification_toolset.verify_citations(
            {"citations": citations}
        )
        summary = verification.get("summary", {})
        failures = [
            r.get("claim_id")
            for r in verification.get("results", [])
            if r.get("severity") in ("dead", "major_fabrication")
        ]

        gaps: list[str] = []
        if ungrounded:
            gaps.append(
                "These citations are not grounded in any tool result -- remove "
                f"them or cite a retrieved work: {', '.join(ungrounded)}."
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
            "summary": summary,
            "gaps": gaps,
        }

    def _gate_scope(self, sections: dict) -> dict:
        """Light, honest scope check.

        We cannot deterministically judge whether a plan fits a budget -- the
        panel's c2 does that -- but we can require the scope & timeline section
        to commit to concrete numbers (a duration or dollar figure) rather than
        hand-wave the fit.
        """
        text = str(sections.get("scope_timeline") or "")
        has_number = bool(re.search(r"\d", text))
        gaps = []
        if not has_number:
            gaps.append(
                "State the budget and timeline concretely (dollar amount and "
                "duration) in the scope & timeline section."
            )
        return {"ok": has_number, "has_number": has_number, "gaps": gaps}

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
        ok = overall >= self.config.panel_threshold
        gaps = []
        if not ok:
            gaps.append(
                f"The judge panel scored this {overall} overall, below the "
                f"{self.config.panel_threshold} bar. Close these gaps: "
                + "; ".join(rollup.get("gaps", []) or ["raise overall quality"])
                + "."
            )
        return {
            "ok": ok,
            "overall": overall,
            "scores": rollup.get("scores"),
            "threshold": self.config.panel_threshold,
            "rollup": rollup,
            "gaps": gaps,
        }
