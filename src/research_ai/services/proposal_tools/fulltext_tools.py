"""On-demand full-text reading for the proposal draft agent.

The profile and the OpenAlex tools give the agent each work's *abstract*; this
toolset lets it read the *full text* of the few works it judges most relevant to
the RFP, without preloading every paper into context. For one work it prefers
ResearchHub's own ``Paper`` (its stored PDF, then its abstract) and falls back
to the OpenAlex open-access PDF, then to the profile abstract.

The reads are capped per run (``max_fetches``) and per call (``_MAX_FULLTEXT_CHARS``)
so deep reading stays bounded in both cost and context.
"""

import logging

from paper.models import Paper
from research_ai.services.agent import Tool
from research_ai.services.pdf_text import (
    extract_text_from_pdf_bytes,
    get_paper_pdf_bytes,
)
from research_ai.services.proposal_tools.doi import strip_doi_prefix

logger = logging.getLogger(__name__)

# Per-run read budget and per-read character ceiling (~6k tokens). Wide enough
# for the body of a paper, bounded so a few deep reads cannot flood the context.
_DEFAULT_MAX_FETCHES = 5
_MAX_FULLTEXT_CHARS = 24000

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "source_url": {
            "type": "string",
            "description": (
                "The work's source_url, exactly as it appears in the researcher "
                "profile (a DOI URL or an OpenAlex work URL)."
            ),
        }
    },
    "required": ["source_url"],
}


def _doi_from_source_url(source_url: str) -> str:
    """Bare, lowercased DOI from a source URL (``""`` when it is not a DOI).

    Strips a known DOI/DOI-URL prefix, then keeps the result only when it looks
    like a DOI (``10.``) -- an OpenAlex work URL or other non-DOI source resolves
    to ``""`` so the caller skips the by-DOI Paper lookup.
    """
    bare = strip_doi_prefix(source_url)
    return bare if bare.startswith("10.") else ""


class ProposalFulltextToolset:
    """A single ``get_work_fulltext`` tool over the researcher's profile works.

    Args:
        search_expert: resolves the ``Expert`` whose profile holds the works
            (their ``pdf_url`` / ``abstract`` and the source_url the agent cites).
        max_fetches: per-run ceiling on full-text reads.
        paper_lookup: injectable ``doi -> Paper | None`` resolver (tests).
    """

    def __init__(
        self,
        search_expert,
        *,
        max_fetches: int = _DEFAULT_MAX_FETCHES,
        paper_lookup=None,
    ):
        self.search_expert = search_expert
        self.max_fetches = max_fetches
        self._paper_lookup = paper_lookup or self._default_paper_lookup
        self._fetches_used = 0
        profile = getattr(search_expert.expert, "profile", None) or {}
        self._works_by_url = {
            str(w.get("source_url") or "").strip(): w
            for w in (profile.get("works") or [])
            if isinstance(w, dict) and str(w.get("source_url") or "").strip()
        }

    # -- tool construction ------------------------------------------------

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name="get_work_fulltext",
                description=(
                    "Read the full text of one of the researcher's works to "
                    "ground the proposal in what the paper actually did. Pass the "
                    "work's source_url from the profile. Prefers the full PDF, "
                    "falling back to the abstract when no readable PDF exists. "
                    f"Limited to {self.max_fetches} reads per run -- spend them on "
                    "the works most relevant to this RFP."
                ),
                input_schema=_INPUT_SCHEMA,
                handler=self._get_work_fulltext,
            )
        ]

    # -- handler ----------------------------------------------------------

    def _get_work_fulltext(self, args: dict) -> dict:
        source_url = str((args or {}).get("source_url") or "").strip()
        if not source_url:
            return {"error": "source_url is required"}

        work = self._works_by_url.get(source_url)
        if work is None:
            return {
                "error": (
                    "Unknown source_url -- it must match a work in the researcher "
                    "profile (call get_researcher_profile to see them)."
                )
            }

        if self._fetches_used >= self.max_fetches:
            return {
                "error": (
                    f"Full-text read budget exhausted ({self.max_fetches} reads). "
                    "Work from the abstracts already in the profile."
                )
            }
        self._fetches_used += 1

        text, content_type = self._resolve_text(source_url, work)
        if not text:
            return {
                "source_url": source_url,
                "content_type": "none",
                "error": "No readable full text or abstract available for this work.",
            }
        truncated = len(text) > _MAX_FULLTEXT_CHARS
        return {
            "source_url": source_url,
            "title": str(work.get("title") or "").strip(),
            "content_type": content_type,
            "truncated": truncated,
            "text": text[:_MAX_FULLTEXT_CHARS] if truncated else text,
        }

    def _resolve_text(self, source_url: str, work: dict) -> tuple[str, str]:
        """Best available (text, content_type) for a work; ``("", "none")`` if none."""
        doi = _doi_from_source_url(source_url)
        paper = self._paper_lookup(doi) if doi else None

        if paper is not None:
            pdf_text = self._pdf_text(getattr(paper, "id", None), paper)
            if pdf_text:
                return pdf_text, "researchhub_pdf"
            paper_abstract = str(getattr(paper, "abstract", "") or "").strip()
            if paper_abstract:
                return paper_abstract, "researchhub_abstract"

        oa_pdf_text = self._pdf_text_from_url(work.get("pdf_url"))
        if oa_pdf_text:
            return oa_pdf_text, "openalex_pdf"

        profile_abstract = str(work.get("abstract") or "").strip()
        if profile_abstract:
            return profile_abstract, "profile_abstract"
        return "", "none"

    # -- fetch helpers (best-effort; never raise into the loop) -----------

    def _pdf_text(self, paper_id, paper) -> str:
        try:
            pdf_bytes = get_paper_pdf_bytes(paper)
            if not pdf_bytes:
                return ""
            return extract_text_from_pdf_bytes(pdf_bytes, max_chars=_MAX_FULLTEXT_CHARS)
        except Exception as exc:  # noqa: BLE001 - a bad PDF must not break the loop
            logger.warning(
                "get_work_fulltext: paper %s PDF read failed: %s", paper_id, exc
            )
            return ""

    def _pdf_text_from_url(self, pdf_url) -> str:
        pdf_url = str(pdf_url or "").strip()
        if not pdf_url:
            return ""
        return self._pdf_text(None, _UrlPaper(pdf_url))

    @staticmethod
    def _default_paper_lookup(doi: str) -> Paper | None:
        if not doi:
            return None
        return Paper.objects.filter(doi__iexact=doi).first()


class _UrlPaper:
    """Minimal duck-typed paper so ``get_paper_pdf_bytes`` can fetch a bare URL."""

    file = None
    external_source = ""
    id = None

    def __init__(self, pdf_url: str):
        self.pdf_url = pdf_url
        self.url = pdf_url
