"""Read-only access to the acting user's public ResearchHub profile.

Agent workflows receive a scoped ``UserProfileToolset`` rather than a user id
chosen by the model.  That makes the identity boundary explicit: the tool can
only return the profile belonging to the user on whose behalf the agent is
already running.
"""

import json

from orcid.identifiers import normalize_orcid
from research_ai.constants import BASE_FRONTEND_URL
from research_ai.services.agent.tools import Tool, Toolset
from utils.openalex import normalize_openalex_id

GET_USER_PROFILE = "get_user_profile"

_EMPTY_INPUT_SCHEMA = {"type": "object", "properties": {}}
_MAX_DESCRIPTION_CHARS = 4000
_MAX_HEADLINE_CHARS = 1000
_MAX_EDUCATION_ENTRIES = 20
_MAX_EDUCATION_ENTRY_BYTES = 2048
_MAX_EDUCATION_PREVIEW_CHARS = 512
_MAX_OPENALEX_IDS = 10
_MAX_ORCID_CHARS = 100


def _text(value, *, max_chars: int | None = None) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    return cleaned if max_chars is None else cleaned[:max_chars]


def _openalex_url(value) -> str | None:
    identifier = normalize_openalex_id(value)
    return f"https://openalex.org/{identifier}" if identifier else None


def _bounded_education(entries) -> list:
    """Keep education useful without letting arbitrary JSON flood a tool result."""
    bounded = []
    for entry in list(entries or [])[:_MAX_EDUCATION_ENTRIES]:
        serialized = json.dumps(entry, allow_nan=False)
        encoded = serialized.encode("utf-8")
        if len(encoded) <= _MAX_EDUCATION_ENTRY_BYTES:
            bounded.append(entry)
            continue
        bounded.append(
            {
                "truncated": True,
                "original_size_bytes": len(encoded),
                "preview": serialized[:_MAX_EDUCATION_PREVIEW_CHARS] + "…",
            }
        )
    return bounded


class UserProfileToolset:
    """Expose the acting user's public author profile to an agent.

    No selector is accepted from the model, so this cannot be used to inspect
    another account.  Email, authentication state, balances, permissions, and
    other private ``User`` fields are deliberately excluded.
    """

    def __init__(self, *, user):
        self._user = user

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name=GET_USER_PROFILE,
                description=(
                    "Read the current user's public ResearchHub author profile. "
                    "Returns their name, bio, affiliation, education, public "
                    "research metrics and identifiers, plus profile pages such "
                    "as ResearchHub, ORCID, OpenAlex, LinkedIn, Google Scholar, "
                    "X/Twitter, and Facebook when supplied. Use it when the "
                    "request benefits from the user's background, expertise, "
                    "publication identity, or public profile links."
                ),
                input_schema=_EMPTY_INPUT_SCHEMA,
                handler=self._get_user_profile,
            )
        ]

    def as_toolset(self) -> Toolset:
        return Toolset(self.build_tools())

    def _get_user_profile(self, _args: dict) -> dict:
        user = self._user
        author = getattr(user, "author_profile", None) if user is not None else None

        user_name = " ".join(
            part
            for part in (
                _text(getattr(user, "first_name", None)),
                _text(getattr(user, "last_name", None)),
            )
            if part
        )
        if author is None:
            return {
                "name": user_name or None,
                "profile": None,
                "identifiers": {},
                "links": {},
            }

        author_name = " ".join(
            part
            for part in (
                _text(getattr(author, "first_name", None)),
                _text(getattr(author, "last_name", None)),
            )
            if part
        )
        university = getattr(author, "university", None)
        orcid_value = _text(
            getattr(author, "orcid_id", None), max_chars=_MAX_ORCID_CHARS
        )
        orcid_url, orcid = normalize_orcid(orcid_value)
        openalex_ids = list(getattr(author, "openalex_ids", None) or [])[
            :_MAX_OPENALEX_IDS
        ]
        openalex_urls = [
            url for url in (_openalex_url(value) for value in openalex_ids) if url
        ]

        links = {
            "researchhub": (
                f"{BASE_FRONTEND_URL.rstrip('/')}/user/{author.id}/overview"
                if getattr(author, "id", None)
                else None
            ),
            "orcid": orcid_url,
            "openalex": openalex_urls,
            "linkedin": _text(getattr(author, "linkedin", None)),
            "google_scholar": _text(getattr(author, "google_scholar", None)),
            "twitter": _text(getattr(author, "twitter", None)),
            "facebook": _text(getattr(author, "facebook", None)),
        }

        return {
            "name": author_name or user_name or None,
            "profile": {
                "id": getattr(author, "id", None),
                "headline": _text(
                    getattr(author, "headline", None), max_chars=_MAX_HEADLINE_CHARS
                ),
                "description": _text(
                    getattr(author, "description", None),
                    max_chars=_MAX_DESCRIPTION_CHARS,
                ),
                "affiliation": (
                    {
                        "name": _text(getattr(university, "name", None)),
                        "city": _text(getattr(university, "city", None)),
                    }
                    if university is not None
                    else None
                ),
                "country_code": _text(getattr(author, "country_code", None)),
                "education": _bounded_education(getattr(author, "education", None)),
                "research_metrics": {
                    "h_index": getattr(author, "h_index", None),
                    "i10_index": getattr(author, "i10_index", None),
                    "two_year_mean_citedness": getattr(
                        author, "two_year_mean_citedness", None
                    ),
                },
            },
            "identifiers": {
                "orcid": orcid,
                "openalex": openalex_urls,
            },
            "links": {key: value for key, value in links.items() if value},
        }
