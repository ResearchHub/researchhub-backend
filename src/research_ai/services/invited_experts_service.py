from datetime import timedelta
from types import SimpleNamespace

from django.db.models import Exists, OuterRef
from django.utils import timezone

from research_ai.constants import EXPERT_REGISTERED_USER_LINK_WINDOW_DAYS
from research_ai.models import Expert, GeneratedEmail, SearchExpert

INVITE_WINDOW_DAYS = 7


def link_experts_registered_user_for_signup(*, normalized_email: str, user) -> int:
    """
    Set ``Expert.registered_user`` for rows matching the signup email when a qualifying
    ``GeneratedEmail`` exists in the link window.
    """
    email = (normalized_email or "").strip().lower()
    if not email:
        return 0

    date_joined = getattr(user, "date_joined", None) or timezone.now()
    window_end = date_joined
    window_start = window_end - timedelta(days=EXPERT_REGISTERED_USER_LINK_WINDOW_DAYS)

    qualifying_ge = GeneratedEmail.objects.filter(
        expert_email__iexact=OuterRef("email"),
        created_date__gte=window_start,
        created_date__lte=window_end,
    ).exclude(status=GeneratedEmail.Status.CLOSED)

    return (
        Expert.objects.filter(
            email__iexact=email,
            registered_user__isnull=True,
        )
        .filter(Exists(qualifying_ge))
        .update(registered_user_id=user.id)
    )


def get_invited_rows_for_unified_document(unified_document_id: int) -> list:
    """
    Users linked as ``Expert.registered_user`` after appearing on an expert search for
    this document. One row per user (most recent ``SearchExpert`` link first).

    Each item has ``user``, ``expert_search_id``, ``generated_email_id`` (or None),
    and ``created_date`` (for ``invited_at``).
    """
    ses = (
        SearchExpert.objects.filter(
            expert_search__unified_document_id=unified_document_id,
            expert__registered_user__isnull=False,
        )
        .select_related("expert", "expert__registered_user", "expert_search")
        .order_by("-created_date")
    )
    by_user: dict[int, SimpleNamespace] = {}
    for se in ses:
        user = se.expert.registered_user
        if user is None or user.id in by_user:
            continue
        ge_id = (
            GeneratedEmail.objects.filter(
                expert_search_id=se.expert_search_id,
                expert_email__iexact=se.expert.email,
            )
            .order_by("-created_date")
            .values_list("id", flat=True)
            .first()
        )
        by_user[user.id] = SimpleNamespace(
            user=user,
            expert_search_id=se.expert_search_id,
            generated_email_id=ge_id,
            created_date=se.created_date,
        )
    return sorted(by_user.values(), key=lambda x: x.created_date, reverse=True)


def materialize_document_invited_experts_for_user(
    *, normalized_email: str, user
) -> None:
    """
    Link ``Expert`` rows for this signup email when outreach qualifies.
    """
    email = (normalized_email or "").strip().lower()
    if not email:
        return

    link_experts_registered_user_for_signup(normalized_email=email, user=user)


def get_document_invite_candidates_for_email(normalized_email, date_joined):
    """
    Return document invite candidates for a normalized email and user join date.

    Returns list of tuples:
        (unified_document_id, expert_search_id, generated_email_id)
    One entry per document (earliest created_date per doc).
    """
    if not normalized_email or not normalized_email.strip():
        return []
    if not date_joined:
        return []

    normalized = normalized_email.strip().lower()
    window_end = date_joined
    window_start = date_joined - timedelta(days=INVITE_WINDOW_DAYS)

    generated = (
        GeneratedEmail.objects.filter(
            expert_search__unified_document_id__isnull=False,
            expert_email__iexact=normalized,
            created_date__gte=window_start,
            created_date__lte=window_end,
        )
        .exclude(status=GeneratedEmail.Status.CLOSED)
        .select_related("expert_search")
        .only("id", "created_date", "expert_search_id")
        .order_by("created_date")
    )

    by_doc = {}
    for ge in generated:
        doc_id = ge.expert_search.unified_document_id if ge.expert_search else None
        if not doc_id or doc_id in by_doc:
            continue
        by_doc[doc_id] = (ge.expert_search_id, ge.id)

    return [(doc_id, es_id, ge_id) for doc_id, (es_id, ge_id) in by_doc.items()]
