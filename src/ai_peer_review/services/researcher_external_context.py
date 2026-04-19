import logging

from orcid.clients import OrcidClient
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import Author
from utils import sentry
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
    """Format a subset of an OpenAlex *Author* JSON object for the peer-review prompt.

    The API returns a large document (ids, counts_by_year, dehydrated relations, etc.).
    We only surface a small, human-readable slice—everything else is dropped:

    - ``display_name``, ``orcid``
    - ``summary_stats``: ``h_index``, ``i10_index``, ``2yr_mean_citedness`` only
    - ``works_count``, ``cited_by_count``
    - ``last_known_institution.display_name``
    - ``affiliations``: first rows (up to 8), unique ``institution.display_name`` (up to 6)
    - ``topics`` / ``x_concepts``: ``display_name`` only (up to 8)

    Author entity field reference: https://developers.openalex.org/api-entities/authors/overview
    """
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
    try:
        return format_openalex_author_record(raw)
    except Exception as exc:
        sentry.log_error(
            exc,
            message="build_researcher_external_context_text: format_openalex_author_record",
        )
        return ""


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


def fetch_orcid_works(
    *,
    orcid_bare: str | None = None,
    client: OrcidClient | None = None,
) -> dict:
    """Load raw ORCID Record ``/works`` JSON (public API). Returns ``{}`` if missing id."""
    oid = (orcid_bare or "").strip()
    if not oid:
        return {}
    oc = client or OrcidClient()
    out = oc.get_works(oid)
    return out if isinstance(out, dict) else {}


def format_orcid_works_payload(works: dict | None) -> str:
    """Format a subset of the ORCID Record ``/works`` JSON for the peer-review prompt.

    The API returns a large nested bulk summary (identifiers, visibility, put-codes,
    multiple ``work-summary`` variants per group, etc.). We only surface a small,
    human-readable slice—everything else is dropped.

    - ``title``: work title string — first non-empty of
      ``title.title.value``, then ``title.value`` (ORCID nests ``Title`` under
      ``title`` in some shapes).
    - ``publication-date``: optional calendar hint — we use ``year`` only, from
      ``publication-date.year.value`` when present (month/day ignored here).

    **Prompt output**

    - One bullet per kept summary: ``- (year) title`` if year is present, else
      ``- title``.
    - At most ``_MAX_ORCID_WORK_LINES`` bullets total, then stop.

    Reading record data (incl. works):
    https://info.orcid.org/documentation/integration-guide/orcid-record/#Works
    and
    https://info.orcid.org/documentation/api-tutorials/api-tutorial-read-data-on-a-record/
    """
    if not works:
        return ""

    lines: list[str] = []
    for group in works.get("group") or []:
        for ws in group.get("work-summary") or []:
            tb = ws.get("title") or {}
            inner = tb.get("title") or {}
            title = str(inner.get("value") or tb.get("value") or "").strip()
            if not title:
                continue
            year = (ws.get("publication-date") or {}).get("year") or {}
            y = str(year.get("value") or "").strip()
            if y:
                lines.append(f"- ({y}) {title}")
            else:
                lines.append(f"- {title}")
            if len(lines) >= _MAX_ORCID_WORK_LINES:
                break
        if len(lines) >= _MAX_ORCID_WORK_LINES:
            break

    if not lines:
        return ""
    return "\n".join(lines)


def build_orcid_works_context_text(
    *,
    orcid_bare: str | None = None,
    client: OrcidClient | None = None,
) -> str:
    """Fetch ORCID ``/works`` and format for the prompt (empty if nothing found)."""
    raw = fetch_orcid_works(orcid_bare=orcid_bare, client=client)
    try:
        return format_orcid_works_payload(raw)
    except Exception as exc:
        sentry.log_error(
            exc,
            message="build_orcid_works_context_text: format_orcid_works_payload",
        )
        return ""


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
        oa_text = build_researcher_external_context_for_author(author)
        if oa_text.strip():
            chunks.append("--- OpenAlex (public author record) ---")
            chunks.append(oa_text.strip())
            chunks.append("")
            has_body = True
    except Exception as e:
        logger.warning(
            "OpenAlex researcher context failed for ORCID %s: %s",
            orcid_id,
            e,
            exc_info=True,
        )

    try:
        works_text = build_orcid_works_context_text(
            orcid_bare=_bare_orcid(author.orcid_id) or author.orcid_id.strip(),
        )
        if works_text.strip():
            chunks.append(
                "--- Recent / listed works (ORCID public record, truncated) ---"
            )
            chunks.append(works_text.strip())
            chunks.append("")
            has_body = True
    except Exception as e:
        logger.warning(
            "ORCID works context failed for %s: %s", orcid_id, e, exc_info=True
        )

    if not has_body:
        return ""

    text = (f"Linked ORCID (ResearchHub): {orcid_id}\n\n" + "\n".join(chunks)).strip()
    if len(text) > max_chars:
        return text[:max_chars] + "\n[TRUNCATED]"
    return text
