import logging
from typing import Any

import requests

from orcid.clients import OrcidClient
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import Author
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 8000
_MAX_ORCID_WORK_LINES = 30


def _orcid_title_value(work_summary: dict) -> str:
    title_block = work_summary.get("title") or {}
    if isinstance(title_block, dict):
        inner = title_block.get("title")
        if isinstance(inner, dict) and inner.get("value"):
            return str(inner["value"]).strip()
        if title_block.get("value"):
            return str(title_block["value"]).strip()
    return ""


def _orcid_year_value(work_summary: dict) -> str:
    pub = work_summary.get("publication-date") or {}
    if not isinstance(pub, dict):
        return ""
    year = pub.get("year")
    if isinstance(year, dict) and year.get("value") is not None:
        return str(year["value"]).strip()
    return ""


def _lines_from_orcid_works(works_payload: dict) -> list[str]:
    lines: list[str] = []
    for group in works_payload.get("group") or []:
        if not isinstance(group, dict):
            continue
        for ws in group.get("work-summary") or []:
            if not isinstance(ws, dict):
                continue
            title = _orcid_title_value(ws)
            if not title:
                continue
            y = _orcid_year_value(ws)
            if y:
                lines.append(f"- ({y}) {title}")
            else:
                lines.append(f"- {title}")
            if len(lines) >= _MAX_ORCID_WORK_LINES:
                return lines
    return lines


# Field names below match the OpenAlex Author object:
# https://docs.openalex.org/api-entities/authors/author-object
def _format_openalex_author(author: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    name = author.get("display_name")
    if name:
        lines.append(f"OpenAlex display name: {name}")
    oid = author.get("id")
    if oid:
        lines.append(f"OpenAlex author id: {oid}")
    orcid = author.get("orcid")
    if orcid:
        lines.append(f"OpenAlex ORCID: {orcid}")

    wc = author.get("works_count")
    cc = author.get("cited_by_count")
    if wc is not None:
        lines.append(f"Works count (OpenAlex): {wc}")
    if cc is not None:
        lines.append(f"Cited-by count (OpenAlex): {cc}")

    stats = author.get("summary_stats") or {}
    if isinstance(stats, dict):
        h = stats.get("h_index")
        i10 = stats.get("i10_index")
        tym = stats.get("2yr_mean_citedness")
        if h is not None:
            lines.append(f"h-index (OpenAlex summary_stats): {h}")
        if i10 is not None:
            lines.append(f"i10-index (OpenAlex): {i10}")
        if tym is not None:
            lines.append(f"2-year mean citedness (OpenAlex): {tym}")

    inst = author.get("last_known_institutions") or []
    if isinstance(inst, list) and inst:
        first = inst[0]
        if isinstance(first, dict):
            iname = first.get("display_name")
            if iname:
                lines.append(f"Last known institution (OpenAlex): {iname}")

    topics = author.get("topics") or []
    if isinstance(topics, list) and topics:
        names: list[str] = []
        for t in topics[:8]:
            if isinstance(t, dict) and t.get("display_name"):
                names.append(str(t["display_name"]))
        if names:
            lines.append("Topic areas (OpenAlex, top): " + "; ".join(names))

    return lines


def build_researcher_external_context(
    unified_document: ResearchhubUnifiedDocument,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """
    Build a bounded text block from ORCID + OpenAlex for the proposal author's linked ORCID.
    Returns "" when there is no owner, no Author row, no orcid_id, or all fetches fail.
    """
    owner = unified_document.created_by
    if not owner:
        return ""
    author = Author.objects.filter(user_id=owner.id).first()
    if not author or not (author.orcid_id or "").strip():
        return ""
    orcid_id = author.orcid_id.strip()
    chunks: list[str] = []
    has_body = False

    try:
        oa = OpenAlex()
        oa_author = oa.get_author_via_orcid(orcid_id)
        if isinstance(oa_author, dict) and oa_author:
            oa_lines = _format_openalex_author(oa_author)
            if oa_lines:
                chunks.append("--- OpenAlex (public author record) ---")
                chunks.extend(oa_lines)
                chunks.append("")
                has_body = True
    except requests.HTTPError as e:
        code = getattr(e.response, "status_code", None)
        if code == 404:
            logger.info(
                "OpenAlex has no author record for ORCID %s (404).",
                orcid_id,
            )
        else:
            logger.warning(
                "OpenAlex author fetch failed for ORCID %s: %s",
                orcid_id,
                e,
                exc_info=True,
            )
    except Exception as e:
        logger.warning(
            "OpenAlex author fetch failed for ORCID %s: %s", orcid_id, e, exc_info=True
        )

    try:
        oc = OrcidClient()
        works = oc.get_works(orcid_id)
        if works and isinstance(works, dict):
            work_lines = _lines_from_orcid_works(works)
            if work_lines:
                chunks.append(
                    "--- Recent / listed works (ORCID public record, truncated) ---"
                )
                chunks.extend(work_lines)
                chunks.append("")
                has_body = True
    except Exception as e:
        logger.warning(
            "ORCID works fetch failed for %s: %s", orcid_id, e, exc_info=True
        )

    if not has_body:
        return ""

    text = (f"Linked ORCID (ResearchHub): {orcid_id}\n\n" + "\n".join(chunks)).strip()
    if len(text) > max_chars:
        return text[:max_chars] + "\n[TRUNCATED]"
    return text
