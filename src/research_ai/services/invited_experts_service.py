from dataclasses import dataclass
from datetime import datetime, timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from research_ai.constants import EXPERT_REGISTERED_USER_LINK_WINDOW_DAYS
from research_ai.models import Expert, ExpertSearch, GeneratedEmail, SearchExpert
from researchhub_access_group.constants import VIEWER
from researchhub_access_group.models import Permission
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

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


def grant_invited_expert_access_for_signup(*, normalized_email: str, user) -> int:
    """
    Create VIEWER ``Permission`` rows on private preregistrations the user was
    invited to via expert finder outreach, when a ``GeneratedEmail`` with
    ``status=SENT`` exists in the link window.
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
            posts__document_type=PREREGISTRATION,
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


@dataclass(frozen=True)
class InvitedExpertOverview:
    experts_total: int = 0
    experts_signed_up: int = 0
    emails_generated: int = 0
    emails_sent: int = 0
    emails_bounced: int = 0
    emails_opened: int = 0


def get_invited_expert_overview(
    *,
    unified_document_id: int | None,
    start: datetime | None,
    end: datetime | None,
) -> InvitedExpertOverview:
    """
    Aggregate invited-expert and outreach-email metrics for ``ExpertSearch`` rows
    filtered by optional document id and ``created_date`` bounds.
    """
    qs = ExpertSearch.objects.all()
    if unified_document_id is not None:
        qs = qs.filter(unified_document_id=unified_document_id)
    if start is not None:
        qs = qs.filter(created_date__gte=start)
    if end is not None:
        qs = qs.filter(created_date__lte=end)

    search_ids = list(qs.values_list("pk", flat=True))
    if not search_ids:
        return InvitedExpertOverview()

    se_agg = SearchExpert.objects.filter(
        expert_search_id__in=search_ids,
    ).aggregate(
        experts_total=Count("expert_id", distinct=True),
        experts_signed_up=Count(
            "expert_id",
            distinct=True,
            filter=Q(expert__registered_user__isnull=False),
        ),
    )

    ge_qs = GeneratedEmail.objects.filter(
        expert_search_id__in=search_ids,
    )
    emails_generated = ge_qs.count()
    emails_sent = ge_qs.filter(
        status=GeneratedEmail.Status.SENT,
    ).count()
    emails_bounced = ge_qs.filter(
        Q(status=GeneratedEmail.Status.BOUNCED) | Q(bounced_at__isnull=False)
    ).count()
    emails_opened = ge_qs.filter(
        Q(opened_at__isnull=False) | Q(open_count__gt=0)
    ).count()

    return InvitedExpertOverview(
        experts_total=se_agg["experts_total"] or 0,
        experts_signed_up=se_agg["experts_signed_up"] or 0,
        emails_generated=emails_generated,
        emails_sent=emails_sent,
        emails_bounced=emails_bounced,
        emails_opened=emails_opened,
    )
