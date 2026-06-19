"""
Cold-start researcher profile builder.

Starts from an ``Expert`` -- names, an ``affiliation``, an ``expertise`` blurb,
and ``sources`` URLs that may carry an ORCID or OpenAlex id. An ``Expert`` is not
a ResearchHub ``Author``, so the existing ``researcher_external_context`` helpers
cannot be called directly -- this package resolves the expert to an OpenAlex
author and builds the profile.

One module per concern:

- ``resolver``       maps the ``Expert`` (cited id links, else name +
                     affiliation) to an OpenAlex author id
- ``works``          fetches and selects the expert's papers (first/last
                     authorship outranks middle, then recency)
- ``builder``        assembles the profile dict and persists it **once** on
                     ``Expert.profile`` so it is reused instead of re-fetched

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
                        | "unresolved",
        "candidates_considered": int,
      },
      "works": [                             # lead-author outrank middle, then recency.
        {"title", "publication_date",        # date orders recency; year is dedup key.
         "publication_year", "source_url",   # author_position: first|middle|last
         "author_position", "pdf_url",       # pdf_url: published-version OA PDF ("" if
         "is_oa"},                           # none); is_oa: work is open access
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
    resolve_openalex_author,
)

__all__ = [
    "AuthorResolution",
    "build_and_store_expert_profile",
    "build_expert_profile",
    "resolve_openalex_author",
]
