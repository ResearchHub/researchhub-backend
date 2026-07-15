"""Bridge completed proposal drafts into expert-finder outreach emails."""

import json
import math
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from invite.models import NoteInvitation
from research_ai.constants import BASE_FRONTEND_URL
from research_ai.models import ExpertSearch, ProposalDraft
from research_ai.services.expert_finder.display import ExpertDisplay
from research_ai.services.outreach.rfp_email_context import (
    build_rfp_context,
    resolve_grant,
)
from researchhub_access_group.constants import EDITOR
from user.models import User

DEFAULT_INVITE_EXPIRATION_MINUTES = 60 * 24 * 30
MAX_PROPOSAL_CONTEXT_CHARS = 20_000
_OUTREACH_TEXT_FIELDS = (
    "funding_topic",
    "fit_summary",
    "data_summary",
    "requested_budget",
    "budget_rationale",
)


class ProposalDraftOutreachError(ValueError):
    """The selected draft cannot be used for this expert outreach."""


@dataclass(frozen=True)
class PreparedProposalOutreach:
    draft: ProposalDraft
    invitation: NoteInvitation
    prompt_context: str
    outreach_context: dict


def proposal_draft_invite_url(invitation: NoteInvitation) -> str:
    return f"{BASE_FRONTEND_URL}/note/join/{invitation.key}"


def resolve_completed_proposal_draft(
    *,
    proposal_draft_id: int,
    expert_search: ExpertSearch,
    expert_email: str,
) -> ProposalDraft:
    try:
        draft = ProposalDraft.objects.select_related(
            "note",
            "note__latest_version",
            "search_expert__expert",
            "search_expert__expert_search",
            "search_expert__expert_search__unified_document",
        ).get(id=proposal_draft_id)
    except ProposalDraft.DoesNotExist as exc:
        raise ProposalDraftOutreachError("Proposal draft not found.") from exc

    if draft.search_expert.expert_search_id != expert_search.id:
        raise ProposalDraftOutreachError(
            "Proposal draft does not belong to this expert search."
        )
    selected_email = ExpertDisplay.normalize_email(expert_email)
    draft_email = ExpertDisplay.normalize_email(draft.search_expert.expert.email)
    if not selected_email or selected_email != draft_email:
        raise ProposalDraftOutreachError(
            "Proposal draft does not belong to this expert."
        )
    if draft.status != ProposalDraft.Status.COMPLETED or draft.note_id is None:
        raise ProposalDraftOutreachError(
            "Proposal draft must be completed before it can be included in an email."
        )
    if draft.note.latest_version_id is None:
        raise ProposalDraftOutreachError("Proposal draft note has no content.")
    if not str(draft.note.latest_version.plain_text or "").strip():
        raise ProposalDraftOutreachError("Proposal draft note has no readable content.")
    if resolve_grant(expert_search=expert_search) is None:
        raise ProposalDraftOutreachError(
            "Proposal outreach requires a funding round linked to the expert search."
        )
    return draft


def _invite_expiration_minutes(draft: ProposalDraft) -> int:
    default_minutes = int(
        getattr(
            settings,
            "PROPOSAL_DRAFT_INVITE_EXPIRATION_MINUTES",
            DEFAULT_INVITE_EXPIRATION_MINUTES,
        )
    )
    grant = resolve_grant(expert_search=draft.search_expert.expert_search)
    if grant is None or grant.end_date is None:
        return max(1, default_minutes)
    until_deadline = math.ceil((grant.end_date - timezone.now()).total_seconds() / 60)
    return max(1, until_deadline)


def _normalize_outreach_context(context: dict | None) -> dict:
    raw = context if isinstance(context, dict) else {}
    normalized = {}
    for field in _OUTREACH_TEXT_FIELDS:
        value = str(raw.get(field) or "").strip()
        if value:
            normalized[field] = value[:2_000]

    highlights = raw.get("highlights") or []
    if isinstance(highlights, list):
        normalized_highlights = [
            str(value).strip()[:1_000]
            for value in highlights[:5]
            if str(value or "").strip()
        ]
        if normalized_highlights:
            normalized["highlights"] = normalized_highlights
    return normalized


def create_proposal_note_invitation(
    *, draft: ProposalDraft, expert_email: str, inviter
) -> NoteInvitation:
    recipient = User.objects.filter(email__iexact=expert_email).first()
    return NoteInvitation.create(
        expiration_time=_invite_expiration_minutes(draft),
        recipient=recipient,
        recipient_email=ExpertDisplay.normalize_email(expert_email),
        inviter=inviter,
        note=draft.note,
        invite_type=EDITOR,
    )


def build_proposal_draft_prompt_context(
    *,
    draft: ProposalDraft,
    invitation: NoteInvitation,
    outreach_context: dict | None = None,
) -> tuple[str, dict]:
    overrides = _normalize_outreach_context(outreach_context)
    expert_search = draft.search_expert.expert_search
    grant = resolve_grant(expert_search=expert_search)
    rfp_context = build_rfp_context(grant) if grant is not None else {}
    sections = (draft.last_submission or {}).get("sections") or {}
    note_text = str(draft.note.latest_version.plain_text or "").strip()
    if len(note_text) > MAX_PROPOSAL_CONTEXT_CHARS:
        note_text = note_text[:MAX_PROPOSAL_CONTEXT_CHARS].rstrip() + "..."
    proposal_title = str(sections.get("title") or draft.note.title or "").strip()

    lines = [
        "This outreach includes an expert-specific proposal draft.",
        "Use only the facts below. Do not invent datasets, methods, budgets, or fit.",
        f"Draft review and application link: {proposal_draft_invite_url(invitation)}",
        f"Proposal title: {proposal_title}",
    ]
    if rfp_context:
        lines.extend(
            [
                f"Funding round title: {rfp_context.get('title') or 'N/A'}",
                f"Funding available: {rfp_context.get('amount') or 'N/A'}",
                f"Application deadline: {rfp_context.get('deadline') or 'N/A'}",
                f"Funding round link: {rfp_context.get('url') or 'N/A'}",
            ]
        )
    if overrides:
        lines.append(
            "Editor-provided outreach fields (prefer these exact facts):\n"
            + json.dumps(overrides, ensure_ascii=False, indent=2)
        )
    lines.append("Accepted proposal draft:\n" + note_text)
    return "\n".join(lines), overrides


def prepare_proposal_outreach(
    *,
    proposal_draft_id: int,
    expert_search: ExpertSearch,
    expert_email: str,
    inviter,
    outreach_context: dict | None = None,
) -> PreparedProposalOutreach:
    draft = resolve_completed_proposal_draft(
        proposal_draft_id=proposal_draft_id,
        expert_search=expert_search,
        expert_email=expert_email,
    )
    invitation = create_proposal_note_invitation(
        draft=draft,
        expert_email=expert_email,
        inviter=inviter,
    )
    prompt_context, normalized = build_proposal_draft_prompt_context(
        draft=draft,
        invitation=invitation,
        outreach_context=outreach_context,
    )
    return PreparedProposalOutreach(
        draft=draft,
        invitation=invitation,
        prompt_context=prompt_context,
        outreach_context=normalized,
    )
