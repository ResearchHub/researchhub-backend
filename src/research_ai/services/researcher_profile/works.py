"""Works on the profile: fetch, extract, and select the expert's papers.

These works seed proposal generation, so we only keep papers we can actually
read: the fetch asks OpenAlex for open-access works, and selection then drops any
without a usable full-text PDF. Each entity is parsed into a ``utils.openalex.Work``
carrying this author's ``author_position`` ("first" | "middle" | "last"). Selection
keeps the ``_MAX_WORKS`` papers with first/last authorship outranking middle
authorship, then recency.
"""

import logging

from research_ai.services.researcher_profile.resolver import AuthorResolution
from utils.openalex import OpenAlex, Work

logger = logging.getLogger(__name__)

_MAX_WORKS = 5  # papers kept on the profile (first/last author, then recency)
_WORKS_PAGE_SIZE = 50  # recent-works window fetched from OpenAlex before selection


def _select_works(works: list[Work]) -> list[Work]:
    """Drop papers with no full-text ``pdf_url``, rank by lead-authorship then
    recency, dedup by title + year, and keep ``_MAX_WORKS``."""
    readable = [work for work in works if work.pdf_url]

    def rank(work: Work) -> tuple[bool, str]:
        return (work.is_lead_author, work.publication_date)

    ranked = sorted(readable, key=rank, reverse=True)

    deduped: list[Work] = []
    seen: set[tuple[str, str]] = set()
    for work in ranked:
        key = (work.title.lower(), work.publication_year)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(work)

    return deduped[:_MAX_WORKS]


def collect_works(
    resolution: AuthorResolution, *, oa_client: OpenAlex
) -> tuple[list[Work], list[str]]:
    """Fetch and select the profile works for a resolved author.

    Best-effort: failures are returned as error strings, never raised.
    """
    if not resolution.openalex_author_id:
        return [], []
    try:
        works = oa_client.get_works_typed(
            openalex_author_id=resolution.openalex_author_id,
            batch_size=_WORKS_PAGE_SIZE,
            sort="publication_date:desc",
            open_access_only=True,
        )
    except Exception as exc:  # noqa: BLE001 - works listing is best-effort
        logger.info("OpenAlex works fetch failed: %s", exc)
        return [], [f"openalex-works: {exc}"]
    return _select_works(works), []
