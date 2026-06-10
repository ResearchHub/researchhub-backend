"""Works on the profile: fetch, extract, and select the expert's papers.

OpenAlex is the primary source because its work entities carry this author's
``author_position`` ("first" | "middle" | "last"); ORCID work summaries don't,
so ORCID is the fallback when OpenAlex has nothing. Selection keeps the
``_MAX_WORKS`` papers with first/last authorship outranking middle authorship,
then recency.
"""

import logging

from research_ai.services.researcher_external_context import fetch_orcid_works
from research_ai.services.researcher_profile.common import is_http_url
from research_ai.services.researcher_profile.resolver import AuthorResolution
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

_MAX_WORKS = 5  # papers kept on the profile (first/last author, then recency)
_WORKS_PAGE_SIZE = 50  # recent-works window fetched from OpenAlex before selection


def _work_year(work: dict) -> int:
    try:
        return int(work.get("year") or 0)
    except (TypeError, ValueError):
        return 0


def work_label(work: dict) -> str:
    label = f"({work['year']}) {work['title']}" if work.get("year") else work["title"]
    position = work.get("author_position")
    if position in ("first", "last"):
        label += f" [{position} author]"
    return label


def _select_works(works: list[dict]) -> list[dict]:
    """Keep ``_MAX_WORKS``: first/last-author papers outrank middle, then recency."""

    def rank(work: dict) -> tuple[int, int]:
        lead = 1 if work.get("author_position") in ("first", "last") else 0
        return (lead, _work_year(work))

    return sorted(works, key=rank, reverse=True)[:_MAX_WORKS]


def _norm_openalex_id(value: str | None) -> str:
    s = str(value or "").strip().lower()
    if "openalex.org/" in s:
        s = s.split("openalex.org/", 1)[-1]
    return s.strip("/")


def _author_position(work: dict, author_id: str | None) -> str | None:
    """This author's position ("first" | "middle" | "last") on an OpenAlex work."""
    target = _norm_openalex_id(author_id)
    if not target:
        return None
    for authorship in work.get("authorships") or []:
        author = (authorship or {}).get("author") or {}
        if _norm_openalex_id(author.get("id")) == target:
            return authorship.get("author_position") or None
    return None


def _extract_openalex_works(results: list[dict], author_id: str | None) -> list[dict]:
    """Map OpenAlex work entities to profile works, with this author's position."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for work in results or []:
        title = str(work.get("display_name") or "").strip()
        if not title:
            continue
        year = str(work.get("publication_year") or "").strip()
        url = str(work.get("doi") or "").strip() or str(work.get("id") or "").strip()
        if not is_http_url(url):
            continue
        key = (title.lower(), year)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "title": title,
                "year": year,
                "source_url": url,
                "author_position": _author_position(work, author_id),
            }
        )
    return out


def _orcid_work_url(work_summary: dict) -> str | None:
    ext = (work_summary.get("external-ids") or {}).get("external-id") or []
    for entry in ext:
        if str(entry.get("external-id-type") or "").lower() == "doi":
            doi = str(entry.get("external-id-value") or "").strip()
            if doi:
                return f"https://doi.org/{doi}"
    url = (work_summary.get("url") or {}).get("value")
    url = str(url or "").strip()
    return url if is_http_url(url) else None


def _extract_orcid_works(works_json: dict | None, orcid_url: str | None) -> list[dict]:
    """Fallback works source when OpenAlex has none (no authorship positions)."""
    collected: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for group in (works_json or {}).get("group") or []:
        for ws in group.get("work-summary") or []:
            tb = ws.get("title") or {}
            inner = tb.get("title") or {}
            title = str(inner.get("value") or tb.get("value") or "").strip()
            if not title:
                continue
            year = str(
                ((ws.get("publication-date") or {}).get("year") or {}).get("value")
                or ""
            ).strip()
            url = _orcid_work_url(ws) or orcid_url
            if not url:
                continue
            # A group lists the same work once per claiming source.
            key = (title.lower(), year)
            if key in seen:
                continue
            seen.add(key)
            collected.append(
                {
                    "title": title,
                    "year": year,
                    "source_url": url,
                    "author_position": None,  # not in ORCID work summaries
                }
            )
    return _select_works(collected)


def collect_works(
    resolution: AuthorResolution, *, oa_client: OpenAlex
) -> tuple[list[dict], list[str]]:
    """Fetch and select the profile works for a resolved author.

    Best-effort: failures are returned as error strings, never raised.
    """
    errors: list[str] = []
    works: list[dict] = []
    if resolution.openalex_author_id:
        try:
            results, _ = oa_client.get_works(
                openalex_author_id=resolution.openalex_author_id,
                batch_size=_WORKS_PAGE_SIZE,
                sort="publication_date:desc",
            )
            works = _select_works(
                _extract_openalex_works(results, resolution.openalex_author_id)
            )
        except Exception as exc:  # noqa: BLE001 - works listing is best-effort
            logger.info("OpenAlex works fetch failed: %s", exc)
            errors.append(f"openalex-works: {exc}")
    if not works and resolution.orcid:
        orcid_works_json: dict = {}
        try:
            orcid_works_json = fetch_orcid_works(orcid_bare=resolution.orcid)
        except Exception as exc:  # noqa: BLE001 - ORCID is best-effort
            logger.info("ORCID works fetch failed: %s", exc)
            errors.append(f"orcid: {exc}")
        works = _extract_orcid_works(
            orcid_works_json, f"https://orcid.org/{resolution.orcid}"
        )
    return works, errors
