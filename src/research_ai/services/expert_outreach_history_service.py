from dataclasses import dataclass

from research_ai.models import GeneratedEmail
from research_ai.services.expert_display import ExpertDisplay
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)


@dataclass(frozen=True)
class DocumentOutreachMeta:
    unified_document_id: int
    document_type: str
    title: str
    slug: str
    id: int


@dataclass(frozen=True)
class ExpertOutreachDocumentRef:
    unified_document_id: int
    document_type: str
    title: str
    slug: str
    id: int
    sent_at: str
    search_id: int


@dataclass(frozen=True)
class ExpertCurrentDocumentOutreach:
    sent_at: str
    search_id: int


@dataclass(frozen=True)
class ExpertOutreachHistory:
    emailed_for_current_document: ExpertCurrentDocumentOutreach | None
    emailed_on_other_documents: list[ExpertOutreachDocumentRef]


def _document_meta_from_unified_doc(
    unified_doc: ResearchhubUnifiedDocument,
) -> DocumentOutreachMeta | None:
    try:
        doc = unified_doc.get_document()
        if doc is None:
            return None
        return DocumentOutreachMeta(
            unified_document_id=unified_doc.id,
            document_type=unified_doc.document_type,
            title=unified_doc.get_display_title(),
            slug=unified_doc.get_document_slug(),
            id=doc.id,
        )
    except Exception:
        return None


def build_expert_outreach_history_map(
    *,
    expert_emails: list[str],
    current_unified_document_id: int | None,
) -> dict[str, ExpertOutreachHistory]:
    """
    Return per-email outreach history from sent ``GeneratedEmail`` rows.

    ``emailed_for_current_document`` is scoped to ``current_unified_document_id``.
    ``emailed_on_other_documents`` lists the latest send per other linked document.
    """
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in expert_emails:
        email = ExpertDisplay.normalize_email(raw)
        if email and email not in seen:
            seen.add(email)
            normalized.append(email)

    if not normalized:
        return {}

    rows = (
        GeneratedEmail.objects.filter(
            expert_email__in=normalized,
            status=GeneratedEmail.Status.SENT,
            expert_search__isnull=False,
        )
        .select_related("expert_search__unified_document")
        .order_by("-updated_date", "-id")
    )

    current_by_email: dict[str, ExpertCurrentDocumentOutreach] = {}
    other_by_email_doc: dict[str, dict[int, ExpertOutreachDocumentRef]] = {}
    doc_meta_cache: dict[int, DocumentOutreachMeta | None] = {}

    for row in rows:
        email = ExpertDisplay.normalize_email(row.expert_email or "")
        if not email:
            continue

        expert_search = row.expert_search
        unified_doc = getattr(expert_search, "unified_document", None)
        unified_doc_id = getattr(unified_doc, "id", None)
        sent_at = row.updated_date.isoformat() if row.updated_date else ""
        search_id = expert_search.id

        if unified_doc_id is None:
            continue

        if (
            current_unified_document_id is not None
            and unified_doc_id == current_unified_document_id
        ):
            if email not in current_by_email:
                current_by_email[email] = ExpertCurrentDocumentOutreach(
                    sent_at=sent_at,
                    search_id=search_id,
                )
            continue

        if unified_doc_id not in doc_meta_cache:
            doc_meta_cache[unified_doc_id] = _document_meta_from_unified_doc(
                unified_doc
            )
        meta = doc_meta_cache[unified_doc_id]
        if meta is None:
            continue

        per_email = other_by_email_doc.setdefault(email, {})
        if unified_doc_id in per_email:
            continue

        per_email[unified_doc_id] = ExpertOutreachDocumentRef(
            unified_document_id=meta.unified_document_id,
            document_type=meta.document_type,
            title=meta.title,
            slug=meta.slug,
            id=meta.id,
            sent_at=sent_at,
            search_id=search_id,
        )

    out: dict[str, ExpertOutreachHistory] = {}
    for email in normalized:
        out[email] = ExpertOutreachHistory(
            emailed_for_current_document=current_by_email.get(email),
            emailed_on_other_documents=list(other_by_email_doc.get(email, {}).values()),
        )
    return out
