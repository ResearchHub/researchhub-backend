"""Assemble and persist the profile: record fields, claims, context text.

The entry points live here: ``build_expert_profile`` (no write) and
``build_and_store_expert_profile`` (persists on ``Expert.profile``).
"""

import logging

from django.utils import timezone

from research_ai.services.researcher_external_context import (
    format_openalex_author_record,
)
from research_ai.services.researcher_profile.common import (
    candidate_institution_names,
    is_http_url,
    search_name,
)
from research_ai.services.researcher_profile.resolver import (
    AuthorResolution,
    resolve_openalex_author,
)
from research_ai.services.researcher_profile.works import collect_works, work_label
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1
_MAX_AFFILIATIONS = 8
_MAX_TOPICS = 10
_CONTEXT_MAX_CHARS = 8000


def _extract_metrics(record: dict | None) -> dict:
    if not record:
        return {}
    ss = record.get("summary_stats") or {}
    metrics = {
        "h_index": ss.get("h_index"),
        "i10_index": ss.get("i10_index"),
        "two_year_mean_citedness": ss.get("2yr_mean_citedness"),
        "works_count": record.get("works_count"),
        "cited_by_count": record.get("cited_by_count"),
    }
    if all(v is None for v in metrics.values()):
        return {}
    metrics["source_url"] = record.get("id")
    return metrics


def _extract_affiliations(record: dict | None) -> list[str]:
    if not record:
        return []
    out: list[str] = []
    for name in candidate_institution_names(record):
        name = (name or "").strip()
        if name and name not in out:
            out.append(name)
        if len(out) >= _MAX_AFFILIATIONS:
            break
    return out


def _extract_topics(record: dict | None) -> list[str]:
    if not record:
        return []
    out: list[str] = []
    for source in (record.get("topics") or [], record.get("x_concepts") or []):
        for item in source:
            label = ((item or {}).get("display_name") or "").strip()
            if label and label not in out:
                out.append(label)
            if len(out) >= _MAX_TOPICS:
                return out
        if out:
            break
    return out


def _build_claims(
    *,
    author_url: str | None,
    metrics: dict,
    affiliations: list[str],
    topics: list[str],
    works: list[dict],
) -> list[dict]:
    """Flatten every fact into ``{text, url}``; drop anything without a real URL."""
    claims: list[dict] = []

    def add(text: str, url: str | None) -> None:
        text = (text or "").strip()
        url = (url or "").strip()
        if text and is_http_url(url):
            claims.append({"text": text, "url": url})

    if metrics:
        h, i10 = metrics.get("h_index"), metrics.get("i10_index")
        if h is not None or i10 is not None:
            add(f"OpenAlex h-index {h}, i10-index {i10}", author_url)
        wc, cbc = metrics.get("works_count"), metrics.get("cited_by_count")
        if wc is not None or cbc is not None:
            add(f"OpenAlex works_count {wc}, cited_by_count {cbc}", author_url)
    for name in affiliations:
        add(f"Affiliation (OpenAlex): {name}", author_url)
    if topics:
        add("Research topics (OpenAlex): " + ", ".join(topics[:8]), author_url)
    for work in works:
        add(work_label(work), work.get("source_url"))

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for claim in claims:
        key = (claim["text"].lower(), claim["url"].lower())
        if key not in seen:
            seen.add(key)
            out.append(claim)
    return out


def _build_context_text(
    expert,
    resolution: AuthorResolution,
    record: dict | None,
    works_text: str,
    *,
    max_chars: int = _CONTEXT_MAX_CHARS,
) -> str:
    chunks: list[str] = []

    head = [f"Researcher profile: {search_name(expert)}".rstrip(": ")]
    if resolution.openalex_author_id:
        head.append(f"OpenAlex author: {resolution.openalex_author_id}")
    chunks.append("\n".join(head))

    oa_text = format_openalex_author_record(record) if record else ""
    if oa_text.strip():
        chunks.append("--- OpenAlex (public author record) ---\n" + oa_text.strip())

    if works_text.strip():
        chunks.append(
            "--- Selected works (first/last-author papers prioritized) ---\n"
            + works_text.strip()
        )

    text = "\n\n".join(c for c in chunks if c.strip()).strip()
    if len(text) > max_chars:
        return text[:max_chars] + "\n[TRUNCATED]"
    return text


def build_expert_profile(
    expert,
    *,
    oa_client: OpenAlex | None = None,
    adjudication_service=None,
) -> dict:
    """
    Build the source-attributed researcher profile for an ``Expert`` (no write).

    Resolver -> OpenAlex author record -> OpenAlex works. Every stage is
    best-effort: failures are captured in ``errors`` and the profile is
    still returned with whatever was found.
    """
    errors: list[str] = []
    oa = oa_client or OpenAlex()
    try:
        resolution = resolve_openalex_author(
            expert, client=oa, adjudication_service=adjudication_service
        )
    except Exception as exc:  # noqa: BLE001 - resolver is best-effort
        logger.exception("resolve_openalex_author failed")
        resolution = AuthorResolution(match_method="unresolved")
        errors.append(f"resolve: {exc}")
    if resolution.error:
        errors.append(f"resolve: {resolution.error}")

    record = resolution.record
    metrics = _extract_metrics(record)
    affiliations = _extract_affiliations(record)
    topics = _extract_topics(record)

    works, works_errors = collect_works(resolution, oa_client=oa)
    errors.extend(works_errors)
    works_text = "\n".join(f"- {work_label(w)}" for w in works)

    context_text = _build_context_text(expert, resolution, record, works_text)
    claims = _build_claims(
        author_url=resolution.openalex_author_id,
        metrics=metrics,
        affiliations=affiliations,
        topics=topics,
        works=works,
    )

    return {
        "schema_version": _SCHEMA_VERSION,
        "built_at": timezone.now().isoformat(),
        "resolution": resolution.as_dict(),
        "metrics": metrics,
        "affiliations": affiliations,
        "topics": topics,
        "works": works,
        "claims": claims,
        "context_text": context_text,
        "errors": errors,
    }


def build_and_store_expert_profile(expert, **kwargs) -> dict:
    """Build the profile and persist it on ``Expert.profile`` (built once, reused)."""
    profile = build_expert_profile(expert, **kwargs)
    expert.profile = profile
    expert.save(update_fields=["profile", "updated_date"])
    return profile
