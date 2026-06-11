"""Works on the profile: fetch, extract, and select the expert's papers.

Works come from the OpenAlex works API; each entity is parsed into a
``utils.openalex.Work`` carrying this author's ``author_position``
("first" | "middle" | "last"). Selection keeps the ``_MAX_WORKS`` papers
with first/last authorship outranking middle authorship, then recency.
"""

import logging

from research_ai.services.researcher_profile.resolver import AuthorResolution
from utils.openalex import OpenAlex, Work

logger = logging.getLogger(__name__)

_MAX_WORKS = 5  # papers kept on the profile (first/last author, then recency)
_WORKS_PAGE_SIZE = 50  # recent-works window fetched from OpenAlex before selection


def _select_works(works: list[Work]) -> list[Work]:
    """Keep ``_MAX_WORKS``: first/last-author papers outrank middle, then recency."""

    def rank(work: Work) -> tuple[bool, int]:
        return (work.is_lead_author, work.year_int)

    return sorted(works, key=rank, reverse=True)[:_MAX_WORKS]


def _extract_openalex_works(results: list[dict], author_id: str | None) -> list[Work]:
    """Parse OpenAlex work entities, deduped by title + year."""
    out: list[Work] = []
    seen: set[tuple[str, str]] = set()
    for entity in results or []:
        work = Work.from_openalex(entity, author_id=author_id)
        if work is None:
            continue
        key = (work.title.lower(), work.year)
        if key in seen:
            continue
        seen.add(key)
        out.append(work)
    return out


def collect_works(
    resolution: AuthorResolution, *, oa_client: OpenAlex
) -> tuple[list[Work], list[str]]:
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
