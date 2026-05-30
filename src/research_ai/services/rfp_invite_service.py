import logging
from dataclasses import dataclass

from django.db import transaction
from django.template.loader import render_to_string

from research_ai.models import ExpertSearch, GeneratedEmail, SearchExpert
from research_ai.services.expert_display import ExpertDisplay
from research_ai.services.expert_persist import ExpertPersist
from research_ai.services.rfp_email_context import build_rfp_context

logger = logging.getLogger(__name__)

INVITE_SEARCH_NAME = "RFP Applicant Invites"
SUBJECT_TEMPLATE = "research_ai/email/rfp_applicant_invite_subject.txt"
BODY_TEMPLATE = "research_ai/email/rfp_applicant_invite_body.html"


@dataclass
class InviteResult:
    generated_email_ids: list[int]
    skipped_existing: list[str]


def _render_email(*, grant, inviter) -> tuple[str, str]:
    rfp = build_rfp_context(grant)
    full_name = getattr(inviter, "get_full_name", lambda: "")() or ""
    inviter_name = full_name.strip() or "A ResearchHub editor"
    context = {
        "inviter_name": inviter_name,
        "rfp_title": rfp.get("title") or "",
        "rfp_amount": rfp.get("amount") or "",
        "rfp_deadline": rfp.get("deadline") or "",
        "rfp_url": rfp.get("url") or "",
        "rfp_description": rfp.get("description_snippet") or "",
        "rfp_organization": (grant.organization or "").strip(),
    }
    subject = render_to_string(SUBJECT_TEMPLATE, context).strip()
    body = render_to_string(BODY_TEMPLATE, context)
    return subject, body


def _get_or_create_invite_search(*, grant, inviter) -> ExpertSearch:
    """One ExpertSearch per (inviter, grant) so the existing access-grant flow
    and per-editor analytics work without creating a new row per invite call.
    """
    search, _ = ExpertSearch.objects.get_or_create(
        created_by=inviter,
        unified_document=grant.unified_document,
        name=INVITE_SEARCH_NAME,
        defaults={
            "query": INVITE_SEARCH_NAME,
            "input_type": ExpertSearch.InputType.CUSTOM_QUERY,
            "status": ExpertSearch.Status.COMPLETED,
            "progress": 100,
        },
    )
    return search


def invite_applicants(*, grant, inviter, emails: list[str]) -> InviteResult:
    """Create Expert + GeneratedEmail rows (status=SENDING) for each email.

    The caller is expected to enqueue ``send_queued_emails_task`` with the
    returned ids. ``skipped_existing`` lists emails that already have a SENT or
    in-flight invite on this grant so we don't email anyone twice.
    """
    subject, body = _render_email(grant=grant, inviter=inviter)
    search = _get_or_create_invite_search(grant=grant, inviter=inviter)

    normalized_emails = []
    seen = set()
    for raw in emails:
        em = ExpertDisplay.normalize_email(raw or "")
        if em and em not in seen:
            seen.add(em)
            normalized_emails.append(em)

    already_in_flight = set(
        GeneratedEmail.objects.filter(
            expert_search=search,
            expert_email__in=normalized_emails,
        )
        .exclude(
            status__in=[
                GeneratedEmail.Status.FAILED,
                GeneratedEmail.Status.SEND_FAILED,
                GeneratedEmail.Status.CLOSED,
            ]
        )
        .values_list("expert_email", flat=True)
    )

    created_ids: list[int] = []
    with transaction.atomic():
        for position, email in enumerate(normalized_emails):
            if email in already_in_flight:
                continue
            expert = ExpertPersist.upsert_from_parsed_dict({"email": email})
            ExpertPersist.tag_manual_source(expert, inviter)
            SearchExpert.objects.get_or_create(
                expert_search=search,
                expert=expert,
                defaults={"position": position},
            )
            ge = GeneratedEmail.objects.create(
                created_by=inviter,
                expert_search=search,
                expert_email=email,
                expert_name=ExpertDisplay.display_name_for(expert),
                expert_title=expert.academic_title or "",
                expert_affiliation=expert.affiliation or "",
                email_subject=subject,
                email_body=body,
                template=None,
                status=GeneratedEmail.Status.SENDING,
            )
            created_ids.append(ge.id)

    return InviteResult(
        generated_email_ids=created_ids,
        skipped_existing=sorted(already_in_flight),
    )
