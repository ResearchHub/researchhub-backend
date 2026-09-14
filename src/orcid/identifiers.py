"""Canonical representations of ORCID identifiers."""

from orcid.config.constants import ORCID_BASE_URL


def normalize_orcid(orcid: str | None) -> tuple[str | None, str | None]:
    """Normalize an ORCID to ``(public_url, bare_id)``.

    ResearchHub historically stores both bare identifiers and full public
    URLs.  Keeping the conversion here gives every ORCID-owning service one
    representation boundary.
    """
    raw = str(orcid or "").strip().rstrip("/")
    if not raw:
        return None, None

    marker = "orcid.org/"
    marker_index = raw.lower().find(marker)
    bare = raw[marker_index + len(marker) :] if marker_index >= 0 else raw
    bare = bare.strip("/")
    if not bare:
        return None, None
    return f"{ORCID_BASE_URL}/{bare}", bare
