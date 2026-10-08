"""Resolve author emails from structured scholarly metadata.

Sources:
1. OpenAlex authorship ``raw_affiliation_strings`` (sometimes embed emails)
2. If none found: Europe PMC core record by DOI, then Crossref work by DOI
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote

from utils.retryable_requests import retryable_requests_session

logger = logging.getLogger(__name__)

_TIMEOUT = 8
_EMAIL_RE = re.compile(
    r"(?i)\b([a-z0-9][a-z0-9._%+\-]{0,63}@[a-z0-9][a-z0-9.\-]{1,250}\.[a-z]{2,24})\b"
)
_CROSSREF_URL = "https://api.crossref.org/works/{doi}"
_EUROPE_PMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
# Polite-pool contact for Crossref (public product inbox).
_CROSSREF_MAILTO = "hello@researchhub.com"


def normalize_doi(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if lower.startswith(prefix):
            return raw[len(prefix) :].strip()
    return raw


def emails_in_text(text: str | None) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for match in _EMAIL_RE.finditer(text):
        email = _normalize_email(match.group(1))
        if not email or email in seen or not _looks_like_person_email(email):
            continue
        seen.add(email)
        out.append(email)
    return out


def emails_from_openalex_authorships(authorships: list | None) -> list[dict]:
    """Emails embedded in OpenAlex affiliation strings, keyed by author id."""
    found: list[dict] = []
    seen: set[str] = set()
    for authorship in authorships or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        author_id = str(author.get("id") or "").strip()
        display = str(author.get("display_name") or "").strip()
        blobs = list(authorship.get("raw_affiliation_strings") or [])
        for aff in authorship.get("affiliations") or []:
            if isinstance(aff, dict) and aff.get("raw_affiliation_string"):
                blobs.append(aff["raw_affiliation_string"])
        for blob in blobs:
            for email in emails_in_text(str(blob or "")):
                key = f"{author_id}:{email}"
                if key in seen:
                    continue
                seen.add(key)
                found.append(
                    {
                        "email": email,
                        "openalex_author_id": author_id or None,
                        "display_name": display or None,
                        "source": "openalex_affiliation",
                        "is_corresponding": bool(authorship.get("is_corresponding")),
                    }
                )
    return found


def lookup_work_emails(
    *,
    doi: str | None,
    authorships: list | None = None,
    session=None,
) -> list[dict]:
    """OpenAlex first; Europe PMC / Crossref only when OpenAlex has no email."""
    hits = emails_from_openalex_authorships(authorships)
    if hits:
        return _dedupe_hits(hits)

    bare_doi = normalize_doi(doi)
    if not bare_doi:
        return []

    own_session = session is None
    http = session or retryable_requests_session(total_retries=1, backoff_factor=0.2)
    try:
        hits.extend(_europe_pmc_emails(bare_doi, session=http))
        if hits:
            return _dedupe_hits(hits)
        hits.extend(_crossref_emails(bare_doi, session=http))
    finally:
        if own_session:
            try:
                http.close()
            except Exception:  # noqa: BLE001
                pass
    return _dedupe_hits(hits)


def bind_emails_to_authors(
    authors: list[dict],
    email_hits: list[dict],
) -> list[dict]:
    """Attach ``metadata_email`` onto author cards when a hit matches."""
    if not authors or not email_hits:
        return authors
    by_id: dict[str, str] = {}
    by_last: dict[str, str] = {}
    unbound: list[str] = []
    for hit in email_hits:
        email = _normalize_email(hit.get("email"))
        if not email:
            continue
        author_id = str(hit.get("openalex_author_id") or "").strip().lower()
        if author_id:
            bare = author_id.rsplit("/", 1)[-1]
            by_id[bare] = email
            by_id[author_id] = email
        last = _last_name(hit.get("display_name"))
        if last and last not in by_last:
            by_last[last] = email
        if hit.get("is_corresponding") and email not in unbound:
            unbound.append(email)

    corresponding_ids = {
        _bare_id(a.get("openalex_author_id"))
        for a in authors
        if a.get("is_corresponding")
    }
    corresponding_ids.discard("")

    for author in authors:
        if author.get("metadata_email"):
            continue
        bare = _bare_id(author.get("openalex_author_id"))
        email = by_id.get(bare) or by_id.get(
            str(author.get("openalex_author_id") or "").lower()
        )
        if not email:
            last = _last_name(author.get("display_name"))
            email = by_last.get(last) if last else None
        if not email and author.get("is_corresponding") and len(unbound) == 1:
            email = unbound[0]
        if not email and len(email_hits) == 1 and len(corresponding_ids) == 1:
            if bare in corresponding_ids:
                email = _normalize_email(email_hits[0].get("email"))
        if email:
            author["metadata_email"] = email
            author["metadata_email_source"] = next(
                (
                    h.get("source")
                    for h in email_hits
                    if _normalize_email(h.get("email")) == email
                ),
                "metadata",
            )
    return authors


def _europe_pmc_emails(doi: str, *, session) -> list[dict]:
    try:
        response = session.get(
            _EUROPE_PMC_URL,
            params={
                "query": f'DOI:"{doi}"',
                "resultType": "core",
                "format": "json",
                "pageSize": 1,
            },
            timeout=_TIMEOUT,
        )
        if response.status_code >= 400:
            return []
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.info("europe pmc email lookup failed doi=%s err=%s", doi, exc)
        return []
    results = (
        ((payload or {}).get("resultList") or {}).get("result")
        if isinstance(payload, dict)
        else None
    )
    if not results:
        return []
    record = results[0] if isinstance(results[0], dict) else {}
    out: list[dict] = []
    for author in (record.get("authorList") or {}).get("author") or []:
        if not isinstance(author, dict):
            continue
        display = str(author.get("fullName") or "").strip() or " ".join(
            p
            for p in (
                str(author.get("firstName") or "").strip(),
                str(author.get("lastName") or "").strip(),
            )
            if p
        )
        blobs = [str(author.get("affiliation") or "")]
        for detail in (author.get("authorAffiliationDetailsList") or {}).get(
            "authorAffiliation"
        ) or []:
            if isinstance(detail, dict):
                blobs.append(str(detail.get("affiliation") or ""))
        for blob in blobs:
            for email in emails_in_text(blob):
                out.append(
                    {
                        "email": email,
                        "openalex_author_id": None,
                        "display_name": display or None,
                        "source": "europe_pmc",
                        "is_corresponding": False,
                    }
                )
    return out


def _crossref_emails(doi: str, *, session) -> list[dict]:
    try:
        response = session.get(
            _CROSSREF_URL.format(doi=quote(doi, safe="/")),
            params={"mailto": _CROSSREF_MAILTO},
            headers={"Accept": "application/json"},
            timeout=_TIMEOUT,
        )
        if response.status_code >= 400:
            return []
        message = (response.json() or {}).get("message") or {}
    except Exception as exc:  # noqa: BLE001
        logger.info("crossref email lookup failed doi=%s err=%s", doi, exc)
        return []
    out: list[dict] = []
    for author in message.get("author") or []:
        if not isinstance(author, dict):
            continue
        display = " ".join(
            p
            for p in (
                str(author.get("given") or "").strip(),
                str(author.get("family") or "").strip(),
            )
            if p
        )
        is_corr = "corresponding" in {
            str(r).lower() for r in (author.get("role") or [])
        } or bool(author.get("sequence") == "first" and author.get("corresponding"))
        blobs = [str(author.get("email") or "")]
        for aff in author.get("affiliation") or []:
            if isinstance(aff, dict):
                blobs.append(str(aff.get("name") or ""))
            else:
                blobs.append(str(aff or ""))
        for blob in blobs:
            for email in emails_in_text(blob):
                out.append(
                    {
                        "email": email,
                        "openalex_author_id": None,
                        "display_name": display or None,
                        "source": "crossref",
                        "is_corresponding": is_corr,
                    }
                )
    return out


def _dedupe_hits(hits: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for hit in hits:
        email = _normalize_email(hit.get("email"))
        if not email:
            continue
        key = (
            f"{email}|{_bare_id(hit.get('openalex_author_id'))}|"
            f"{_last_name(hit.get('display_name'))}"
        )
        if key in seen:
            continue
        seen.add(key)
        out.append({**hit, "email": email})
    return out


def _normalize_email(value: str | None) -> str:
    return str(value or "").strip().lower().rstrip(".,;:)")


def _looks_like_person_email(email: str) -> bool:
    if "@" not in email or email.endswith((".png", ".jpg", ".gif", ".svg", ".webp")):
        return False
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        return False
    if local in {"example", "email", "name", "user", "username", "info", "contact"}:
        return False
    if domain in {"example.com", "email.com", "domain.com", "sentry.io"}:
        return False
    return True


def _last_name(display_name: str | None) -> str:
    parts = [p for p in str(display_name or "").strip().split() if p]
    return parts[-1].casefold() if parts else ""


def _bare_id(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return raw.rsplit("/", 1)[-1]
