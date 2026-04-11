from research_ai.models import GeneratedEmail, SearchExpert


def _latest_generated_email_id_by_search_and_email(
    expert_search_ids: set[int],
) -> dict[tuple[int, str], int]:
    """Most recent non-closed GeneratedEmail id per (expert_search_id, normalized email)."""
    if not expert_search_ids:
        return {}
    mapping: dict[tuple[int, str], int] = {}
    rows = (
        GeneratedEmail.objects.filter(expert_search_id__in=expert_search_ids)
        .exclude(status=GeneratedEmail.Status.CLOSED)
        .order_by("-created_date")
        .values_list("expert_search_id", "expert_email", "id")
    )
    for es_id, raw_email, ge_id in rows:
        em = (raw_email or "").strip().lower()
        if not em:
            continue
        key = (es_id, em)
        if key not in mapping:
            mapping[key] = ge_id
    return mapping


def get_document_invited_rows(
    unified_document_id: int,
    *,
    limit: int | None = None,
) -> tuple[list[dict], int]:
    """
    Experts linked to this unified document (via ExpertSearch → SearchExpert) who
    have registered_user set (RH account tied to that expert email).

    Returns (rows_newest_first, total_count). Each row:
    user (registered_user), expert_search_id, generated_email_id (latest matching
    outreach row if any, else None), invited_at (user.date_joined).
    """
    memberships = list(
        SearchExpert.objects.filter(
            expert_search__unified_document_id=unified_document_id,
            expert__registered_user__isnull=False,
        ).select_related(
            "expert",
            "expert__registered_user",
            "expert__registered_user__author_profile",
        )
    )
    search_ids = {m.expert_search_id for m in memberships}
    ge_by_key = _latest_generated_email_id_by_search_and_email(search_ids)
    rows: list[dict] = []
    for m in memberships:
        user = m.expert.registered_user
        em = (m.expert.email or "").strip().lower()
        rows.append(
            {
                "user": user,
                "expert_search_id": m.expert_search_id,
                "generated_email_id": ge_by_key.get((m.expert_search_id, em)),
                "invited_at": user.date_joined,
            }
        )
    rows.sort(key=lambda r: r["invited_at"], reverse=True)
    total_count = len(rows)
    if limit is not None:
        rows = rows[:limit]
    return rows, total_count
