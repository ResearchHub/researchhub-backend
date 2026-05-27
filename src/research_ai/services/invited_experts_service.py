from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from research_ai.constants import EXPERT_REGISTERED_USER_LINK_WINDOW_DAYS
from research_ai.models import Expert, ExpertSearch, GeneratedEmail, SearchExpert
from researchhub_access_group.constants import VIEWER
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)

INVITE_ACCESS_DOC_TYPES = (PREREGISTRATION, GRANT)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User

INVITE_WINDOW_DAYS = 7
DEFAULT_OVERVIEW_WINDOW_DAYS = 30

EDITOR_SORT_FIELDS = frozenset(
    {
        "experts_total",
        "emails_sent",
        "searches_total",
        "signup_rate",
        "open_rate",
    }
)

_EMAIL_BOUNCED_Q = Q(status=GeneratedEmail.Status.BOUNCED) | Q(bounced_at__isnull=False)
_EMAIL_OPENED_Q = Q(opened_at__isnull=False) | Q(open_count__gt=0)


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


def grant_invited_expert_access_for_signup(*, normalized_email: str, user) -> int:
    """
    Create VIEWER ``Permission`` rows on private preregistrations and private
    grants the user was invited to via expert finder / RFP outreach, when a
    ``GeneratedEmail`` with ``status=SENT`` exists in the link window.
    """
    email = (normalized_email or "").strip().lower()
    if not email:
        return 0

    date_joined = getattr(user, "date_joined", None) or timezone.now()
    window_end = date_joined
    window_start = window_end - timedelta(days=EXPERT_REGISTERED_USER_LINK_WINDOW_DAYS)

    invited_doc_ids = (
        GeneratedEmail.objects.filter(
            expert_email__iexact=email,
            status=GeneratedEmail.Status.SENT,
            created_date__gte=window_start,
            created_date__lte=window_end,
            expert_search__unified_document__isnull=False,
        )
        .values_list("expert_search__unified_document_id", flat=True)
        .distinct()
    )

    qualifying_doc_ids = list(
        ResearchhubUnifiedDocument.objects.filter(
            id__in=invited_doc_ids,
            is_public=False,
            posts__document_type__in=INVITE_ACCESS_DOC_TYPES,
        )
        .values_list("id", flat=True)
        .distinct()
    )
    if not qualifying_doc_ids:
        return 0

    content_type = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
    granted = 0
    for doc_id in qualifying_doc_ids:
        _, created = Permission.objects.get_or_create(
            content_type=content_type,
            object_id=doc_id,
            user=user,
            defaults={"access_type": VIEWER},
        )
        if created:
            granted += 1
    return granted


def grant_invited_expert_access_for_send(*, generated_email) -> bool:
    """
    Grant VIEWER access on the invite's private preregistration or private
    grant when the expert is already a registered user.

    Counterpart to ``grant_invited_expert_access_for_signup``: that function
    runs on signup and only covers users who created their account *after*
    being invited. This one covers users who already existed at invite time
    — they never fire the post-signup signal, so without this hook they'd
    never receive access despite getting the email.

    Returns True if a new Permission row was created.
    """
    expert_search = getattr(generated_email, "expert_search", None)
    if expert_search is None or expert_search.unified_document_id is None:
        return False

    email = (getattr(generated_email, "expert_email", "") or "").strip().lower()
    if not email:
        return False

    expert = (
        Expert.objects.filter(
            email__iexact=email,
            registered_user__isnull=False,
        )
        .select_related("registered_user")
        .first()
    )
    if expert is None:
        return False

    doc_qualifies = ResearchhubUnifiedDocument.objects.filter(
        id=expert_search.unified_document_id,
        is_public=False,
        posts__document_type__in=INVITE_ACCESS_DOC_TYPES,
    ).exists()
    if not doc_qualifies:
        return False

    content_type = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
    _, created = Permission.objects.get_or_create(
        content_type=content_type,
        object_id=expert_search.unified_document_id,
        user=expert.registered_user,
        defaults={"access_type": VIEWER},
    )
    return created


def link_experts_for_new_user(*, normalized_email: str, user) -> None:
    """
    Link ``Expert`` rows for this signup email when outreach qualifies, and
    grant access to any private preregistrations the user was invited to.
    """
    email = (normalized_email or "").strip().lower()
    if not email:
        return

    link_experts_registered_user_for_signup(normalized_email=email, user=user)
    grant_invited_expert_access_for_signup(normalized_email=email, user=user)


def default_overview_date_range() -> tuple[datetime, datetime]:
    """Return aware (start, end) for the default last-30-days window."""
    tz = timezone.get_current_timezone()
    end_date = timezone.localdate()
    start_date = end_date - timedelta(days=DEFAULT_OVERVIEW_WINDOW_DAYS)
    start = timezone.make_aware(datetime.combine(start_date, time.min), tz)
    end = timezone.make_aware(datetime.combine(end_date, time.max), tz)
    return start, end


def invited_stats_cache_key(prefix: str, **parts) -> str:
    segments = [f"{key}={parts[key]}" for key in sorted(parts)]
    return f"invited_expert_{prefix}:" + ":".join(segments)


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _filtered_expert_searches(
    *,
    unified_document_id: int | None,
    start: datetime | None,
    end: datetime | None,
    editor_id: int | None = None,
):
    qs = ExpertSearch.objects.all()
    if unified_document_id is not None:
        qs = qs.filter(unified_document_id=unified_document_id)
    if start is not None:
        qs = qs.filter(created_date__gte=start)
    if end is not None:
        qs = qs.filter(created_date__lte=end)
    if editor_id is not None:
        qs = qs.filter(created_by_id=editor_id)
    return qs


def _email_aggregate_qs(ge_qs):
    return ge_qs.aggregate(
        emails_generated=Count("id"),
        emails_sent=Count("id", filter=Q(status=GeneratedEmail.Status.SENT)),
        emails_bounced=Count("id", filter=_EMAIL_BOUNCED_Q),
        emails_opened=Count("id", filter=_EMAIL_OPENED_Q),
    )


@dataclass(frozen=True)
class InvitedExpertOverview:
    experts_total: int = 0
    experts_signed_up: int = 0
    emails_generated: int = 0
    emails_sent: int = 0
    emails_bounced: int = 0
    emails_opened: int = 0
    proposals_opened: int = 0


@dataclass(frozen=True)
class InvitedExpertOverviewSummary:
    searches_total: int = 0
    searches_completed: int = 0
    searches_failed: int = 0
    searches_pending: int = 0
    signup_rate: float | None = None
    email_send_rate: float | None = None
    open_rate: float | None = None
    bounce_rate: float | None = None


@dataclass(frozen=True)
class InvitedExpertOverviewResult:
    counts: InvitedExpertOverview
    summary: InvitedExpertOverviewSummary


@dataclass(frozen=True)
class InvitedExpertEditorRow:
    user_id: int
    searches_total: int = 0
    searches_completed: int = 0
    experts_total: int = 0
    experts_signed_up: int = 0
    emails_generated: int = 0
    emails_sent: int = 0
    emails_opened: int = 0
    emails_bounced: int = 0
    proposals_outreach_count: int = 0
    emails_sent_by_proposal: dict[int, int] = field(default_factory=dict)
    signup_rate: float | None = None
    open_rate: float | None = None
    bounce_rate: float | None = None


@dataclass(frozen=True)
class InvitedExpertEditorsOverview:
    items: list[InvitedExpertEditorRow] = field(default_factory=list)
    total: int = 0
    limit: int = 5
    offset: int = 0
    sort_by: str = "experts_total"
    sort_order: str = "desc"


def _registered_user_ids(filtered_qs) -> list[int]:
    """Distinct RH user IDs for invited experts who signed up."""
    return list(
        SearchExpert.objects.filter(expert_search__in=filtered_qs)
        .exclude(expert__registered_user_id__isnull=True)
        .values_list("expert__registered_user_id", flat=True)
        .distinct()
    )


def _count_proposals_opened(registered_user_ids: list[int]) -> int:
    """Count PREREGISTRATION posts created by registered invited experts."""
    if not registered_user_ids:
        return 0

    return (
        ResearchhubPost.objects.filter(
            document_type=PREREGISTRATION,
            created_by_id__in=registered_user_ids,
            unified_document__is_removed=False,
        )
        .distinct()
        .count()
    )


def _aggregate_global_counts(filtered_qs) -> InvitedExpertOverview:
    if not filtered_qs.exists():
        return InvitedExpertOverview()

    se_agg = SearchExpert.objects.filter(expert_search__in=filtered_qs).aggregate(
        experts_total=Count("expert_id", distinct=True),
        experts_signed_up=Count(
            "expert_id",
            distinct=True,
            filter=Q(expert__registered_user__isnull=False),
        ),
    )
    registered_user_ids = _registered_user_ids(filtered_qs)
    ge_agg = _email_aggregate_qs(
        GeneratedEmail.objects.filter(expert_search__in=filtered_qs)
    )

    return InvitedExpertOverview(
        experts_total=se_agg["experts_total"] or 0,
        experts_signed_up=se_agg["experts_signed_up"] or 0,
        emails_generated=ge_agg["emails_generated"] or 0,
        emails_sent=ge_agg["emails_sent"] or 0,
        emails_bounced=ge_agg["emails_bounced"] or 0,
        emails_opened=ge_agg["emails_opened"] or 0,
        proposals_opened=_count_proposals_opened(registered_user_ids),
    )


def _build_summary(
    filtered_qs, counts: InvitedExpertOverview
) -> InvitedExpertOverviewSummary:
    if not filtered_qs.exists():
        return InvitedExpertOverviewSummary()

    search_agg = filtered_qs.aggregate(
        searches_total=Count("id"),
        searches_completed=Count("id", filter=Q(status=ExpertSearch.Status.COMPLETED)),
        searches_failed=Count("id", filter=Q(status=ExpertSearch.Status.FAILED)),
        searches_pending=Count(
            "id",
            filter=Q(
                status__in=(
                    ExpertSearch.Status.PENDING,
                    ExpertSearch.Status.PROCESSING,
                )
            ),
        ),
    )

    return InvitedExpertOverviewSummary(
        searches_total=search_agg["searches_total"] or 0,
        searches_completed=search_agg["searches_completed"] or 0,
        searches_failed=search_agg["searches_failed"] or 0,
        searches_pending=search_agg["searches_pending"] or 0,
        signup_rate=_safe_rate(counts.experts_signed_up, counts.experts_total),
        email_send_rate=_safe_rate(counts.emails_sent, counts.emails_generated),
        open_rate=_safe_rate(counts.emails_opened, counts.emails_sent),
        bounce_rate=_safe_rate(counts.emails_bounced, counts.emails_sent),
    )


def get_invited_expert_overview(
    *,
    unified_document_id: int | None,
    start: datetime | None,
    end: datetime | None,
    editor_id: int | None = None,
) -> InvitedExpertOverviewResult:
    """Global KPI counts and summary for filtered expert searches."""
    filtered_qs = _filtered_expert_searches(
        unified_document_id=unified_document_id,
        start=start,
        end=end,
        editor_id=editor_id,
    )
    counts = _aggregate_global_counts(filtered_qs)
    summary = _build_summary(filtered_qs, counts)
    return InvitedExpertOverviewResult(counts=counts, summary=summary)


def _emails_sent_by_proposal_per_editor(filtered_qs) -> dict[int, dict[int, int]]:
    """Map editor user_id -> {unified_document_id: sent email count} for PREREGISTRATION outreach."""
    rows = (
        GeneratedEmail.objects.filter(
            expert_search__in=filtered_qs,
            status=GeneratedEmail.Status.SENT,
            expert_search__unified_document_id__isnull=False,
            expert_search__unified_document__document_type=PREREGISTRATION,
        )
        .values(
            "expert_search__created_by_id",
            "expert_search__unified_document_id",
        )
        .annotate(emails_sent=Count("id"))
    )
    per_editor: dict[int, dict[int, int]] = {}
    for row in rows:
        editor_id = row["expert_search__created_by_id"]
        proposal_id = row["expert_search__unified_document_id"]
        per_editor.setdefault(editor_id, {})[proposal_id] = row["emails_sent"] or 0
    return per_editor


def _merge_editor_metrics(
    *,
    search_rows: list[dict],
    expert_rows: list[dict],
    email_rows: list[dict],
    proposal_rows: list[dict],
) -> dict[int, dict[str, int]]:
    merged: dict[int, dict[str, int]] = {}

    def _ensure(user_id: int) -> dict[str, int]:
        if user_id not in merged:
            merged[user_id] = {
                "searches_total": 0,
                "searches_completed": 0,
                "experts_total": 0,
                "experts_signed_up": 0,
                "emails_generated": 0,
                "emails_sent": 0,
                "emails_opened": 0,
                "emails_bounced": 0,
                "proposals_outreach_count": 0,
            }
        return merged[user_id]

    for row in search_rows:
        user_id = row["created_by_id"]
        bucket = _ensure(user_id)
        bucket["searches_total"] = row.get("searches_total") or 0
        bucket["searches_completed"] = row.get("searches_completed") or 0

    for row in expert_rows:
        user_id = row["expert_search__created_by_id"]
        bucket = _ensure(user_id)
        bucket["experts_total"] = row.get("experts_total") or 0
        bucket["experts_signed_up"] = row.get("experts_signed_up") or 0

    for row in email_rows:
        user_id = row["expert_search__created_by_id"]
        bucket = _ensure(user_id)
        bucket["emails_generated"] = row.get("emails_generated") or 0
        bucket["emails_sent"] = row.get("emails_sent") or 0
        bucket["emails_opened"] = row.get("emails_opened") or 0
        bucket["emails_bounced"] = row.get("emails_bounced") or 0

    for row in proposal_rows:
        user_id = row["created_by_id"]
        bucket = _ensure(user_id)
        bucket["proposals_outreach_count"] = row.get("proposals_outreach_count") or 0

    return merged


def _editor_row_from_metrics(
    user_id: int,
    metrics: dict[str, int],
    *,
    emails_sent_by_proposal: dict[int, int] | None = None,
) -> InvitedExpertEditorRow:
    experts_total = metrics["experts_total"]
    experts_signed_up = metrics["experts_signed_up"]
    emails_sent = metrics["emails_sent"]
    emails_bounced = metrics["emails_bounced"]
    emails_opened = metrics["emails_opened"]
    proposals_outreach_count = metrics["proposals_outreach_count"]
    return InvitedExpertEditorRow(
        user_id=user_id,
        searches_total=metrics["searches_total"],
        searches_completed=metrics["searches_completed"],
        experts_total=experts_total,
        experts_signed_up=experts_signed_up,
        emails_generated=metrics["emails_generated"],
        emails_sent=emails_sent,
        emails_opened=emails_opened,
        emails_bounced=emails_bounced,
        proposals_outreach_count=proposals_outreach_count,
        emails_sent_by_proposal=emails_sent_by_proposal or {},
        signup_rate=_safe_rate(experts_signed_up, experts_total),
        open_rate=_safe_rate(emails_opened, emails_sent),
        bounce_rate=_safe_rate(emails_bounced, emails_sent),
    )


def _sort_editor_rows(
    rows: list[InvitedExpertEditorRow], *, sort_by: str, sort_order: str
) -> list[InvitedExpertEditorRow]:
    reverse = sort_order != "asc"

    def _sort_key(row: InvitedExpertEditorRow):
        if sort_by in ("signup_rate", "open_rate"):
            value = getattr(row, sort_by)
            return (value is None, value if value is not None else -1)
        return getattr(row, sort_by, 0)

    return sorted(rows, key=_sort_key, reverse=reverse)


def get_invited_expert_editors_overview(
    *,
    unified_document_id: int | None,
    start: datetime | None,
    end: datetime | None,
    limit: int = 5,
    offset: int = 0,
    sort_by: str = "experts_total",
    sort_order: str = "desc",
    min_searches: int = 1,
) -> InvitedExpertEditorsOverview:
    """Paginated per-editor metrics for filtered expert searches."""
    filtered_qs = _filtered_expert_searches(
        unified_document_id=unified_document_id,
        start=start,
        end=end,
    )

    if not filtered_qs.exists():
        return InvitedExpertEditorsOverview(
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    search_rows = list(
        filtered_qs.values("created_by_id")
        .annotate(
            searches_total=Count("id"),
            searches_completed=Count(
                "id", filter=Q(status=ExpertSearch.Status.COMPLETED)
            ),
        )
        .filter(searches_total__gte=min_searches)
    )

    expert_rows = list(
        SearchExpert.objects.filter(expert_search__in=filtered_qs)
        .values("expert_search__created_by_id")
        .annotate(
            experts_total=Count("expert_id", distinct=True),
            experts_signed_up=Count(
                "expert_id",
                distinct=True,
                filter=Q(expert__registered_user__isnull=False),
            ),
        )
    )

    email_rows = list(
        GeneratedEmail.objects.filter(expert_search__in=filtered_qs)
        .values("expert_search__created_by_id")
        .annotate(
            emails_generated=Count("id"),
            emails_sent=Count("id", filter=Q(status=GeneratedEmail.Status.SENT)),
            emails_bounced=Count("id", filter=_EMAIL_BOUNCED_Q),
            emails_opened=Count("id", filter=_EMAIL_OPENED_Q),
        )
    )

    proposal_rows = list(
        filtered_qs.values("created_by_id").annotate(
            proposals_outreach_count=Count(
                "unified_document_id",
                distinct=True,
                filter=Q(
                    unified_document_id__isnull=False,
                    unified_document__document_type=PREREGISTRATION,
                ),
            ),
        )
    )

    merged = _merge_editor_metrics(
        search_rows=search_rows,
        expert_rows=expert_rows,
        email_rows=email_rows,
        proposal_rows=proposal_rows,
    )
    emails_sent_by_proposal = _emails_sent_by_proposal_per_editor(filtered_qs)

    editor_ids = {row["created_by_id"] for row in search_rows}
    all_rows = [
        _editor_row_from_metrics(
            user_id,
            merged[user_id],
            emails_sent_by_proposal=emails_sent_by_proposal.get(user_id, {}),
        )
        for user_id in editor_ids
        if user_id in merged
    ]
    sorted_rows = _sort_editor_rows(all_rows, sort_by=sort_by, sort_order=sort_order)
    total = len(sorted_rows)
    page_rows = sorted_rows[offset : offset + limit]

    return InvitedExpertEditorsOverview(
        items=page_rows,
        total=total,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
    )


def load_editor_users(user_ids: list[int]) -> dict[int, User]:
    if not user_ids:
        return {}
    users = User.objects.filter(id__in=user_ids).select_related("author_profile")
    return {user.id: user for user in users}
