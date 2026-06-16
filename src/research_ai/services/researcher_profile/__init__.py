"""
Cold-start researcher profile builder.

Starts from an ``Expert`` -- names, an ``affiliation``, an ``expertise`` blurb,
and ``sources`` URLs that may carry an ORCID or OpenAlex id. An ``Expert`` is not
a ResearchHub ``Author``, so the existing ``researcher_external_context`` helpers
cannot be called directly -- this package resolves the expert to an OpenAlex
author and builds the profile.

One module per concern:

- ``resolver``       maps the ``Expert`` to an OpenAlex author id via the full
                     escalation ladder (cited id links, else name + affiliation,
                     else LLM disambiguation); ``resolve_author`` is the entry
- ``disambiguator``  hands ambiguous candidate sets to the LLM, which picks the
                     matching author or abstains
- ``works``          fetches and selects a resolved author's papers (first/last
                     authorship outranks middle, then recency)
- ``builder``        delegates resolution, then assembles the profile dict and
                     persists it **once** on ``Expert.profile``

The resolver escalates only as far as needed (source-link -> name -> LLM
disambiguation), stopping at the first confident rung, so the LLM runs at most
once per expert; an expert that still cannot be matched is left ``unresolved``.

**Every work is readable** -- works seed proposal generation, so the list is
restricted to open-access papers that expose a full-text ``pdf_url`` (the most
authoritative version available), each with a ``source_url`` to cite.

``Expert.profile`` schema (JSON, ``schema_version`` 1)::

    {
      "schema_version": 1,
      "built_at": "<ISO 8601>",
      "resolution": {
        "openalex_author_id": str | None,
        "display_name": str | None,
        "match_score": float,                # 0..1
        "match_method": "source-link" | "name+affiliation" | "name"
                        | "name-llm" | "unresolved",
        "candidates_considered": int,
        "disambiguation": {                  # present only when the LLM was consulted
          "confidence": float,               # 0..1, the model's stated confidence
          "reasoning": str,                  # one-sentence rationale
          "chosen": bool,                    # False when the model abstained
        },
      },
      "works": [                             # lead-author outrank middle, then recency.
        {"title", "publication_date",        # date orders recency; year dedups.
         "publication_year", "source_url",   # author_position: first|middle|last|None
         "author_position", "pdf_url",       # pdf_url: published-version OA PDF
         "is_oa"},                           # ("" when none); is_oa: open access
        ...,
      ],
      "errors": [str, ...],                  # non-fatal failures, for auditability
    }
"""

from research_ai.services.researcher_profile.builder import (
    build_and_store_expert_profile,
    build_expert_profile,
)
from research_ai.services.researcher_profile.resolver import (
    AuthorResolution,
    resolve_author,
)

__all__ = [
    "AuthorResolution",
    "build_and_store_expert_profile",
    "build_expert_profile",
    "resolve_author",
]
