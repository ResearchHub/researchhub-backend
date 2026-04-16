import logging
from typing import Any

import requests
from orcid.clients import OrcidClient
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import Author
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

_MAX_ORCID_WORK_LINES = 30
_DEFAULT_PIPELINE_MAX_CHARS = 8000


def _bare_orcid(author_orcid: str | None) -> str | None:
    if not author_orcid:
        return None
    s = str(author_orcid).strip()
    if "orcid.org/" in s:
        return s.split("orcid.org/", 1)[-1].strip().strip("/")
    return s or None


def _normalize_openalex_author_token(ref: str | None) -> str | None:
    if not ref:
        return None
    r = str(ref).strip()
    if "openalex.org/" in r:
        return r.rstrip("/").rsplit("/", 1)[-1]
    if r.startswith("A"):
        return r
    return None


def fetch_openalex_author_record(
    *,
    orcid_bare: str | None = None,
    openalex_author_ref: str | None = None,
    client: OpenAlex | None = None,
) -> dict | None:
    """
    Load a single OpenAlex author entity, preferring ORCID when provided.

    Returns the raw OpenAlex JSON dict or None if lookup fails.
    """
    oa = client or OpenAlex()
    if orcid_bare:
        try:
            return oa.get_author_via_orcid(orcid_bare)
        except Exception as exc:
            logger.info("OpenAlex author lookup by ORCID failed: %s", exc)

    token = _normalize_openalex_author_token(openalex_author_ref)
    if not token:
        return None
    try:
        return oa._get(f"authors/{token}")
    except Exception as exc:
        logger.info("OpenAlex author lookup by id failed: %s", exc)
        return None


def format_openalex_author_record(record: dict | None) -> str:
    """Turn an OpenAlex author JSON payload into short factual lines."""
    if not record:
        return ""

    lines: list[str] = []
    name = (record.get("display_name") or "").strip()
    if name:
        lines.append(f"OpenAlex display_name: {name}")

    if record.get("orcid"):
        lines.append(f"OpenAlex ORCID: {record['orcid']}")

    ss = record.get("summary_stats") or {}
    if ss:
        lines.append(
            "OpenAlex summary_stats: "
            f"h_index={ss.get('h_index')}, i10_index={ss.get('i10_index')}, "
            f"2yr_mean_citedness={ss.get('2yr_mean_citedness')}"
        )

    wc = record.get("works_count")
    cbc = record.get("cited_by_count")
    if wc is not None or cbc is not None:
        lines.append(f"OpenAlex works_count={wc}, cited_by_count={cbc}")

    last_inst = (record.get("last_known_institution") or {}).get("display_name")
    if last_inst:
        lines.append(f"OpenAlex last_known_institution: {last_inst}")

    affs = record.get("affiliations") or []
    inst_names: list[str] = []
    for aff in affs[:8]:
        inst = aff.get("institution") or {}
        dn = (inst.get("display_name") or "").strip()
        if dn and dn not in inst_names:
            inst_names.append(dn)
    if inst_names:
        lines.append("OpenAlex affiliations (sample): " + "; ".join(inst_names[:6]))

    topics = record.get("topics") or []
    topic_labels: list[str] = []
    for t in topics[:10]:
        label = (t.get("display_name") or "").strip()
        if label:
            topic_labels.append(label)
    if topic_labels:
        lines.append("OpenAlex topics (sample): " + ", ".join(topic_labels[:8]))

    x_concepts = record.get("x_concepts") or []
    concept_labels: list[str] = []
    for c in x_concepts[:10]:
        label = (c.get("display_name") or "").strip()
        if label:
            concept_labels.append(label)
    if concept_labels:
        joined = ", ".join(concept_labels[:8])
        lines.append(f"OpenAlex x_concepts (sample): {joined}")

    return "\n".join(lines).strip()


def build_researcher_external_context_text(
    *,
    orcid_bare: str | None = None,
    openalex_author_ref: str | None = None,
    client: OpenAlex | None = None,
) -> str:
    """
    Public OpenAlex/ORCID facts as prompt-ready text (empty if nothing found).
    """
    raw = fetch_openalex_author_record(
        orcid_bare=orcid_bare,
        openalex_author_ref=openalex_author_ref,
        client=client,
    )
    return format_openalex_author_record(raw)


def build_researcher_external_context_for_author(
    author: Author | None,
    *,
    client: OpenAlex | None = None,
) -> str:
    """
    Resolve ORCID and OpenAlex ids from a ResearchHub Author and build context text.
    """
    if author is None:
        return ""
    orcid = _bare_orcid(getattr(author, "orcid_id", None))
    oa_ref: str | None = None
    ids = getattr(author, "openalex_ids", None) or []
    for oid in ids:
        if oid:
            oa_ref = str(oid)
            break
    return build_researcher_external_context_text(
        orcid_bare=orcid,
        openalex_author_ref=oa_ref,
        client=client,
    )


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


def _format_openalex_author_pipeline(author: dict[str, Any]) -> list[str]:
    """Field names align with OpenAlex Author API entity."""
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
    max_chars: int = _DEFAULT_PIPELINE_MAX_CHARS,
) -> str:
    """
    Bounded ORCID + OpenAlex text for the proposal author's linked ORCID.

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
            oa_lines = _format_openalex_author_pipeline(oa_author)
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
