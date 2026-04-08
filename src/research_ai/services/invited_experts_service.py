from datetime import timedelta

from django.contrib.auth import get_user_model

from research_ai.models import GeneratedEmail

INVITE_WINDOW_DAYS = 7


def get_document_invited_rows(
    unified_document_id: int,
    *,
    limit: int | None = None,
) -> tuple[list[dict], int]:
    """
    Users who signed up within INVITE_WINDOW_DAYS after a generated outreach email
    for this document (same rules as the former DocumentInvitedExpert signal).

    Returns (rows_newest_first, total_count). Each row:
    user, expert_search_id, generated_email_id, invited_at (user.date_joined).
    """
    User = get_user_model()
    rows_by_user: dict[int, dict] = {}
    ges = (
        GeneratedEmail.objects.filter(
            expert_search__unified_document_id=unified_document_id,
        )
        .exclude(status=GeneratedEmail.Status.CLOSED)
        .select_related("expert_search")
        .order_by("created_date")
    )
    for ge in ges:
        raw = (ge.expert_email or "").strip()
        if not raw:
            continue
        window_end = ge.created_date + timedelta(days=INVITE_WINDOW_DAYS)
        for u in User.objects.filter(
            email__iexact=raw,
            date_joined__gte=ge.created_date,
            date_joined__lte=window_end,
        ):
            if u.id in rows_by_user:
                continue
            rows_by_user[u.id] = {
                "user": u,
                "expert_search_id": ge.expert_search_id,
                "generated_email_id": ge.id,
                "invited_at": u.date_joined,
            }
    rows = sorted(
        rows_by_user.values(),
        key=lambda r: r["invited_at"],
        reverse=True,
    )
    total_count = len(rows)
    if limit is not None:
        rows = rows[:limit]
    return rows, total_count


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
