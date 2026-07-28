from datetime import timedelta

from django.db.models import Count, Exists, OuterRef

from research_ai.constants import EXPERT_REGISTERED_USER_LINK_WINDOW_DAYS
from research_ai.models import Expert, GeneratedEmail, ProposalDraft


def get_expert_finder_metrics(period):
    emails = GeneratedEmail.objects.filter(
        created_date__gte=period.start,
        created_date__lt=period.end,
    )
    drafts_completed = ProposalDraft.objects.filter(
        status=ProposalDraft.Status.COMPLETED,
        completed_at__gte=period.start,
        completed_at__lt=period.end,
    )
    qualifying_outreach = GeneratedEmail.objects.filter(
        expert_email__iexact=OuterRef("email"),
        created_date__gte=(
            OuterRef("registered_user__date_joined")
            - timedelta(days=EXPERT_REGISTERED_USER_LINK_WINDOW_DAYS)
        ),
        created_date__lte=OuterRef("registered_user__date_joined"),
    ).exclude(status=GeneratedEmail.Status.CLOSED)
    invited_experts = (
        Expert.objects.filter(
            registered_user__date_joined__gte=period.start,
            registered_user__date_joined__lt=period.end,
        )
        .filter(Exists(qualifying_outreach))
        .values("registered_user_id")
        .distinct()
        .count()
    )
    outreach_by_channel = {choice: 0 for choice, _ in GeneratedEmail.Channel.choices}
    for row in (
        emails.filter(status=GeneratedEmail.Status.SENT)
        .exclude(channel="")
        .values("channel")
        .annotate(count=Count("id"))
    ):
        outreach_by_channel[row["channel"]] = row["count"]

    return {
        "experts_generated_outreach_for": (
            emails.exclude(expert_email="").values("expert_email").distinct().count()
        ),
        "invited_experts": invited_experts,
        "auto_drafted_proposals": drafts_completed.count(),
        "outreach_by_channel": outreach_by_channel,
    }
