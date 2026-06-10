"""Works on the profile: fetch, extract, and select the expert's papers.

Works come from the OpenAlex works API, whose entities carry this author's
``author_position`` ("first" | "middle" | "last"). Selection keeps the
``_MAX_WORKS`` papers with first/last authorship outranking middle authorship,
then recency.
"""

import logging

from research_ai.services.researcher_profile.common import is_http_url
from research_ai.services.researcher_profile.resolver import AuthorResolution
from utils.openalex import OpenAlex, normalize_openalex_id

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


def _author_position(work: dict, author_id: str | None) -> str | None:
    """This author's position ("first" | "middle" | "last") on an OpenAlex work."""
    target = normalize_openalex_id(author_id).lower()
    if not target:
        return None
    for authorship in work.get("authorships") or []:
        author = (authorship or {}).get("author") or {}
        if normalize_openalex_id(author.get("id")).lower() == target:
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


def collect_works(
    resolution: AuthorResolution, *, oa_client: OpenAlex
) -> tuple[list[dict], list[str]]:
    """Fetch and select the profile works for a resolved author.

    Best-effort: failures are returned as error strings, never raised.
    """
    if not resolution.openalex_author_id:
        return [], []
    try:
        results, _ = oa_client.get_works(
            openalex_author_id=resolution.openalex_author_id,
            batch_size=_WORKS_PAGE_SIZE,
            sort="publication_date:desc",
        )
    except Exception as exc:  # noqa: BLE001 - works listing is best-effort
        logger.info("OpenAlex works fetch failed: %s", exc)
        return [], [f"openalex-works: {exc}"]
    works = _select_works(
        _extract_openalex_works(results, resolution.openalex_author_id)
    )
    return works, []
