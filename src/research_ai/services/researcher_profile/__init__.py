"""
Cold-start researcher profile builder for the proposal draft engine (Part 1).

The proposal draft engine starts from an ``Expert`` that has only names, an
``affiliation``, an ``expertise`` blurb, and a few ``sources`` URLs -- it has
*neither* an ORCID nor an OpenAlex id, so the existing
``researcher_external_context`` helpers (which key off a ResearchHub ``Author``)
cannot be called directly.

This package adds the net-new piece, one module per concern:

- ``resolver``       maps the ``Expert`` (known id links, else name +
                     affiliation) to an OpenAlex author id (and ORCID when
                     findable)
- ``adjudication``   conservative LLM verdict for ambiguous resolver candidates
- ``works``          fetches and selects the expert's papers (first/last
                     authorship outranks middle, then recency)
- ``builder``        assembles the profile dict and persists it **once** on
                     ``Expert.profile`` so the generate, verify, and
                     notebook-iteration stages reuse it instead of re-fetching

**Every claim carries a source URL.** The ``claims`` list is the source-attributed
ground truth the draft's credibility (rubric #4) is built on and what the source
verifier (Part 3) later checks against -- entries without a real URL are dropped.

``Expert.profile`` schema (JSON, ``schema_version`` 1)::

    {
      "schema_version": 1,
      "built_at": "<ISO 8601>",
      "resolution": {
        "openalex_author_id": str | None,
        "orcid": str | None,
        "display_name": str | None,
        "match_score": float,                # 0..1
        "match_method": "source-link" | "name+affiliation" | "name"
                        | "llm-adjudicated" | "unresolved",
        "candidates_considered": int,
      },
      "metrics": {                           # {} when unresolved / no stats
        "h_index", "i10_index", "two_year_mean_citedness",
        "works_count", "cited_by_count", "source_url",
      },
      "affiliations": [str, ...],            # OpenAlex institutions
      "topics": [str, ...],                  # OpenAlex topics / concepts
      "works": [                             # first/last-author papers outrank
        {"title", "year", "source_url",      # middle ones, then most recent first;
         "author_position"},                 # "first" | "middle" | "last" | None
        ...,                                 # (None when ORCID is the source)
      ],
      "claims": [{"text", "url"}, ...],      # flat, every entry has a URL
      "context_text": str,                   # prompt-ready block for the generator
      "errors": [str, ...],                  # non-fatal failures, for auditability
    }
"""

from research_ai.services.researcher_profile.builder import (
    build_and_store_expert_profile,
    build_expert_profile,
)
from research_ai.services.researcher_profile.resolver import (
    AuthorResolution,
    resolve_openalex_author,
)

__all__ = [
    "AuthorResolution",
    "build_and_store_expert_profile",
    "build_expert_profile",
    "resolve_openalex_author",
]
