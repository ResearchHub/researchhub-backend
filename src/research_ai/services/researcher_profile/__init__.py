"""Agentic researcher-profile builder.

Starts from a ``ProfileSeed`` -- built from an outreach ``Expert`` and/or a
user's own ``Author`` profile: a name, an affiliation, an expertise blurb,
source URLs, and any ORCID or OpenAlex ids -- and builds a source-attributed
profile of who they are in OpenAlex and what they have published.

An LLM agent (``agent``) drives the work using the OpenAlex tools
(``openalex_tools``): it resolves the expert to the right OpenAlex author and
selects their most relevant readable papers. The agent owns the judgment; the
tools own the ground truth, so every author id and work URL is read from
OpenAlex -- never invented. A grounding pass drops any citation the tools did
not actually return before the profile is stored.

Profiles are stored on ``ResearcherProfile`` (one row per researcher, keyed on
the user and/or the expert) and kept current by ``ResearcherProfileService``.

``ResearcherProfile.data`` schema (JSON, ``schema_version`` 2)::

    {
      "schema_version": 2,
      "built_at": "<ISO 8601>",
      "resolution": {
        "openalex_author_id": str | None,   # null when not confidently resolved
        "display_name": str | None,
        "orcid": str | None,
        "confidence": float,                 # 0..1
        "reasoning": str,
      },
      "works": [                             # up to 5, grounded against tool output
        {"title", "publication_date", "publication_year", "source_url",
         "pdf_url", "author_position", "is_oa"},
        ...,
      ],
      "capabilities": [                      # up to 12, evidence grounded in works
        {"kind", "name", "note", "evidence": [source_url, ...]},
        ...,
      ],
      "errors": [str, ...],                  # non-fatal failures, for auditability
    }
"""

from research_ai.services.researcher_profile.profile_service import (
    ResearcherProfileService,
    schedule_profile_build,
)

__all__ = [
    "ResearcherProfileService",
    "schedule_profile_build",
]
