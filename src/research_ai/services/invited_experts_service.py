from datetime import timedelta

from django.db.models import Exists, OuterRef
from django.utils import timezone

from research_ai.constants import EXPERT_REGISTERED_USER_LINK_WINDOW_DAYS
from research_ai.models import DocumentInvitedExpert, Expert, GeneratedEmail

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


def materialize_document_invited_experts_for_user(
    *, normalized_email: str, user
) -> None:
    """
    Link ``Expert`` rows for this signup email, then create ``DocumentInvitedExpert`` rows
    for document-backed outreach within INVITE_WINDOW_DAYS.
    """
    email = (normalized_email or "").strip().lower()
    if not email:
        return

    date_joined = getattr(user, "date_joined", None)
    if not date_joined:
        return

    link_experts_registered_user_for_signup(normalized_email=email, user=user)

    candidates = get_document_invite_candidates_for_email(email, date_joined)
    for unified_document_id, expert_search_id, generated_email_id in candidates:
        DocumentInvitedExpert.objects.get_or_create(
            unified_document_id=unified_document_id,
            user=user,
            defaults={
                "expert_search_id": expert_search_id,
                "generated_email_id": generated_email_id,
            },
        )


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

    # One per doc, earliest created_date
    by_doc = {}
    for ge in generated:
        doc_id = ge.expert_search.unified_document_id if ge.expert_search else None
        if not doc_id or doc_id in by_doc:
            continue
        by_doc[doc_id] = (ge.expert_search_id, ge.id)

    return [(doc_id, es_id, ge_id) for doc_id, (es_id, ge_id) in by_doc.items()]
