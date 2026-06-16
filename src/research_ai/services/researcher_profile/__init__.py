"""
Cold-start researcher profile builder.

Starts from an ``Expert`` -- names, an ``affiliation``, an ``expertise`` blurb,
and ``sources`` URLs that may carry an ORCID. An ``Expert`` is not a ResearchHub
``Author``, so this package resolves it to an OpenAlex author and builds the
profile. One module per concern: ``resolver`` maps the expert to an author id,
``disambiguator`` is the LLM rung, ``works`` selects the papers, and ``builder``
assembles and persists the profile dict on ``Expert.profile``.

``Expert.profile`` schema (JSON, ``schema_version`` 1)::

    {
      "schema_version": 1,
      "built_at": "<ISO 8601>",
      "resolution": {
        "openalex_author_id": str | None,
        "display_name": str | None,
        "match_score": float,                # 0..1
        "match_method": "source-link" | "name+affiliation" | "name-llm"
                        | "web-id" | "unresolved",
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
