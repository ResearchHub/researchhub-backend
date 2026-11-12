"""What the researcher-profile agent is told about the person it resolves.

A ``ProfileSeed`` is built from an outreach ``Expert``, from a user's own
``Author`` profile, or from both merged. The user's verified ORCID and
OpenAlex ids beat the machine-generated outreach hints, so the author side wins
where both have a value. ``inputs_hash`` fingerprints the seed so a changed
identity triggers a rebuild.
"""

import hashlib
import json
from dataclasses import dataclass

from orcid.identifiers import normalize_orcid
from utils.openalex import normalize_openalex_id

_MAX_EXPERTISE_CHARS = 2000
_MAX_OPENALEX_IDS = 10


@dataclass(frozen=True)
class ProfileSeed:
    name: str = ""
    affiliation: str = ""
    expertise: str = ""
    source_urls: tuple[str, ...] = ()
    orcid: str | None = None
    openalex_ids: tuple[str, ...] = ()

    @property
    def is_buildable(self) -> bool:
        """The agent needs a name or an identifier to search on."""
        return bool(self.name or self.orcid or self.openalex_ids)

    def as_payload(self) -> dict:
        return {
            "name": self.name,
            "affiliation": self.affiliation,
            "expertise": self.expertise,
            "source_urls": list(self.source_urls),
            "cited_orcid": self.orcid,
            "openalex_ids": list(self.openalex_ids),
        }

    def inputs_hash(self) -> str:
        encoded = json.dumps(self.as_payload(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def merged_over(self, fallback: ProfileSeed) -> ProfileSeed:
        """This seed, with blanks filled from ``fallback`` and URLs unioned."""
        return ProfileSeed(
            name=self.name or fallback.name,
            affiliation=self.affiliation or fallback.affiliation,
            expertise=self.expertise or fallback.expertise,
            source_urls=_unique(self.source_urls + fallback.source_urls),
            orcid=self.orcid or fallback.orcid,
            openalex_ids=_unique(self.openalex_ids + fallback.openalex_ids)[
                :_MAX_OPENALEX_IDS
            ],
        )


def seed_from_expert(expert) -> ProfileSeed:
    return ProfileSeed(
        name=(expert.full_name or "").strip(),
        affiliation=_clean(getattr(expert, "affiliation", "")),
        expertise=_clean(getattr(expert, "expertise", ""))[:_MAX_EXPERTISE_CHARS],
        source_urls=_unique(tuple(expert.source_urls)),
        orcid=expert.orcid,
    )


def seed_from_user(user) -> ProfileSeed:
    """Seed from the user's ``Author`` profile, falling back to account names."""
    author = getattr(user, "author_profile", None)
    user_name = " ".join(
        part for part in (_clean(user.first_name), _clean(user.last_name)) if part
    )
    if author is None:
        return ProfileSeed(name=user_name)

    author_name = " ".join(
        part for part in (_clean(author.first_name), _clean(author.last_name)) if part
    )
    university = getattr(author, "university", None)
    orcid_url, orcid = normalize_orcid(author.orcid_id)
    openalex_ids = _unique(
        tuple(
            identifier
            for identifier in (
                normalize_openalex_id(value) for value in author.openalex_ids or []
            )
            if identifier
        )
    )[:_MAX_OPENALEX_IDS]
    source_urls = tuple(
        url
        for url in (
            orcid_url,
            *(f"https://openalex.org/{identifier}" for identifier in openalex_ids),
            _clean(author.google_scholar),
        )
        if url
    )
    expertise = " ".join(
        part for part in (_clean(author.headline), _clean(author.description)) if part
    )
    return ProfileSeed(
        name=author_name or user_name,
        affiliation=_clean(getattr(university, "name", "")),
        expertise=expertise[:_MAX_EXPERTISE_CHARS],
        source_urls=source_urls,
        orcid=orcid.upper() if orcid else None,
        openalex_ids=openalex_ids,
    )


def seed_for_profile(profile) -> ProfileSeed:
    """The seed for a ``ResearcherProfile``: its user's, over its expert's."""
    seed = ProfileSeed()
    if profile.user_id is not None:
        seed = seed_from_user(profile.user)
    if profile.expert_id is not None:
        seed = seed.merged_over(seed_from_expert(profile.expert))
    return seed


def _clean(value) -> str:
    return str(value or "").strip()


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
