from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from research_ai.models import (
    EmailTemplate,
    Expert,
    ExpertSearch,
    GeneratedEmail,
    OutreachCampaign,
    OutreachMailbox,
    SearchExpert,
)
from research_ai.services.expert_finder.display import ExpertDisplay
from research_ai.services.outreach.document_context import (
    resolve_expert_search_email_document_context,
)
from research_ai.services.outreach.instantly_client import (
    DEFAULT_ACCOUNT_DAILY_LIMIT,
    DEFAULT_CAMPAIGN_SCHEDULE,
    InstantlyClient,
    InstantlyNotFoundError,
)
from research_ai.services.outreach.mailbox_service import OutreachMailboxService
from research_ai.services.outreach.template_service import get_template
from research_ai.services.outreach.template_variables import (
    build_replacement_context,
    custom_variables_for_published_keys,
    flatten_placeholders_for_instantly,
    format_expert_name_from_raw,
    missing_published_variables,
    published_variable_keys,
)

if TYPE_CHECKING:
    from user.related_models.user_model import User

logger = logging.getLogger(__name__)

MAX_LEADS_PER_SEND = 1000


class CampaignError(Exception):
    """Base error for campaign publish/list/send operations."""


class CampaignTemplateNotFoundError(CampaignError):
    """Raised when the shared EmailTemplate does not exist."""


class CampaignNotFoundError(CampaignError):
    """Raised when the campaign is missing or not owned by the editor."""


class CampaignNotReadyError(CampaignError):
    """Raised when the campaign cannot accept leads yet."""


class CampaignValidationError(CampaignError):
    """Raised when experts or published variables fail validation."""


class OutreachCampaignService:
    """Publish, list, and send per-editor Instantly campaigns from shared templates."""

    def __init__(
        self,
        *,
        client: InstantlyClient | None = None,
        mailbox_service: OutreachMailboxService | None = None,
    ):
        self.client = client if client is not None else InstantlyClient()
        self.mailbox_service = (
            mailbox_service
            if mailbox_service is not None
            else OutreachMailboxService(client=self.client)
        )

    def list_campaigns(self, editor: User):
        """Return the editor's published campaigns, newest first."""
        return (
            OutreachCampaign.objects.select_related("template", "editor")
            .filter(editor=editor)
            .annotate(
                queued_count=Count(
                    "generated_emails",
                    filter=Q(generated_emails__status=GeneratedEmail.Status.SENDING),
                    distinct=True,
                ),
                sent_count=Count(
                    "generated_emails",
                    filter=Q(generated_emails__status=GeneratedEmail.Status.SENT),
                    distinct=True,
                ),
                opened_count=Count(
                    "generated_emails",
                    filter=Q(generated_emails__opened_at__isnull=False),
                    distinct=True,
                ),
                replied_count=Count(
                    "generated_emails",
                    filter=Q(generated_emails__replied_at__isnull=False),
                    distinct=True,
                ),
                bounced_count=Count(
                    "generated_emails",
                    filter=Q(generated_emails__bounced_at__isnull=False)
                    | Q(generated_emails__status=GeneratedEmail.Status.BOUNCED),
                    distinct=True,
                ),
            )
            .order_by("-updated_date")
        )

    def publish_template(self, editor: User, template_id: int) -> OutreachCampaign:
        """
        Idempotent upsert of one Instantly campaign for ``(editor, template)``.

        Creates and activates on first publish when the editor has active
        mailboxes.
        """
        template = get_template(template_id)
        if template is None:
            raise CampaignTemplateNotFoundError("Template not found.")

        active_emails = list(
            OutreachMailbox.objects.filter(
                editor=editor,
                status=OutreachMailbox.Status.ACTIVE,
            )
            .order_by("email")
            .values_list("email", flat=True)
        )
        daily_limit = DEFAULT_ACCOUNT_DAILY_LIMIT * len(active_emails)
        instantly_subject = flatten_placeholders_for_instantly(
            template.email_subject or ""
        )
        instantly_body = flatten_placeholders_for_instantly(template.email_body or "")
        variable_keys = published_variable_keys(
            template.email_subject or "",
            template.email_body or "",
        )
        campaign_name = _instantly_campaign_name(template, editor)

        with transaction.atomic():
            campaign, _created = (
                OutreachCampaign.objects.select_for_update()
                .select_related("template")
                .get_or_create(
                    editor=editor,
                    template=template,
                    defaults={
                        "published_subject": template.email_subject or "",
                        "published_body": template.email_body or "",
                        "published_variable_keys": variable_keys,
                        "status": (
                            OutreachCampaign.Status.ACTIVE
                            if active_emails
                            else OutreachCampaign.Status.NO_ACTIVE_MAILBOXES
                        ),
                    },
                )
            )

            snapshot_changed = _snapshot_changed(
                campaign,
                template=template,
                variable_keys=variable_keys,
            )

            if not campaign.external_campaign_id:
                self._create_and_maybe_activate(
                    campaign,
                    name=campaign_name,
                    subject=instantly_subject,
                    body=instantly_body,
                    email_list=active_emails,
                    daily_limit=daily_limit,
                )
            else:
                try:
                    self._update_existing(
                        campaign,
                        subject=instantly_subject,
                        body=instantly_body,
                        email_list=active_emails,
                        daily_limit=daily_limit,
                        snapshot_changed=snapshot_changed,
                    )
                except InstantlyNotFoundError:
                    logger.info(
                        "Instantly campaign %s missing; recreating for editor=%s "
                        "template=%s",
                        campaign.external_campaign_id,
                        editor.id,
                        template.id,
                    )
                    campaign.external_campaign_id = ""
                    self._create_and_maybe_activate(
                        campaign,
                        name=campaign_name,
                        subject=instantly_subject,
                        body=instantly_body,
                        email_list=active_emails,
                        daily_limit=daily_limit,
                    )

            campaign.published_subject = template.email_subject or ""
            campaign.published_body = template.email_body or ""
            campaign.published_variable_keys = variable_keys
            campaign.published_at = timezone.now()
            if active_emails:
                campaign.status = OutreachCampaign.Status.ACTIVE
            else:
                campaign.status = OutreachCampaign.Status.NO_ACTIVE_MAILBOXES
            campaign.save(
                update_fields=[
                    "external_campaign_id",
                    "published_subject",
                    "published_body",
                    "published_variable_keys",
                    "published_at",
                    "status",
                    "updated_date",
                ]
            )
            return campaign

    def _create_and_maybe_activate(
        self,
        campaign: OutreachCampaign,
        *,
        name: str,
        subject: str,
        body: str,
        email_list: list[str],
        daily_limit: int,
    ) -> None:
        result = self.client.create_campaign(
            name=name,
            subject=subject,
            body=body,
            email_list=email_list,
            daily_limit=daily_limit,
            campaign_schedule=DEFAULT_CAMPAIGN_SCHEDULE,
        )
        external_id = _extract_campaign_id(result)
        if not external_id:
            raise CampaignError("Instantly create campaign response missing id.")
        campaign.external_campaign_id = external_id
        if email_list:
            self.client.activate_campaign(external_id)

    def _update_existing(
        self,
        campaign: OutreachCampaign,
        *,
        subject: str,
        body: str,
        email_list: list[str],
        daily_limit: int,
        snapshot_changed: bool,
    ) -> None:
        update_kwargs: dict = {
            "email_list": email_list,
            "daily_limit": daily_limit,
        }
        if snapshot_changed:
            update_kwargs.update(
                subject=subject,
                body=body,
                campaign_schedule=DEFAULT_CAMPAIGN_SCHEDULE,
            )
        self.client.update_campaign(campaign.external_campaign_id, **update_kwargs)

        if email_list:
            if campaign.status != OutreachCampaign.Status.ACTIVE:
                self.client.activate_campaign(campaign.external_campaign_id)
        else:
            self.client.pause_campaign(campaign.external_campaign_id)

    def send_to_experts(
        self,
        editor: User,
        campaign_id: int,
        *,
        expert_search_id: int,
        expert_ids: list[int],
    ) -> list[GeneratedEmail]:
        """
        Bulk-add experts as Instantly leads on an existing published campaign.

        Validates ownership, published variables, and remaining daily capacity.
        Creates ``GeneratedEmail`` rows in ``SENDING`` (queued with Instantly).
        """
        if not expert_ids:
            raise CampaignValidationError("At least one expert id is required.")
        if len(expert_ids) > MAX_LEADS_PER_SEND:
            raise CampaignValidationError(
                f"At most {MAX_LEADS_PER_SEND} experts can be sent at once."
            )

        campaign = (
            OutreachCampaign.objects.select_related("template")
            .filter(id=campaign_id, editor=editor)
            .first()
        )
        if campaign is None:
            raise CampaignNotFoundError("Outreach campaign not found.")
        if not campaign.external_campaign_id:
            raise CampaignNotReadyError("Campaign has not been published to Instantly.")
        if campaign.status != OutreachCampaign.Status.ACTIVE:
            raise CampaignNotReadyError(
                f"Campaign is not active (status={campaign.status})."
            )

        try:
            expert_search = ExpertSearch.objects.select_related("unified_document").get(
                id=expert_search_id
            )
        except ExpertSearch.DoesNotExist as exc:
            raise CampaignValidationError("Expert search not found.") from exc

        experts = _load_experts_for_search(expert_search, expert_ids)
        self.mailbox_service.assert_within_daily_capacity(editor, len(experts))

        doc_ctx = resolve_expert_search_email_document_context(expert_search)
        published_keys = list(campaign.published_variable_keys or [])
        prepared: list[tuple[Expert, dict, dict[str, str]]] = []
        for expert in experts:
            resolved = ExpertDisplay.email_generation_dict(expert)
            context = build_replacement_context(
                user=editor,
                resolved_expert=resolved,
                rfp_context_dict=doc_ctx.rfp_context_dict,
                proposal_context_dict=doc_ctx.proposal_context_dict,
            )
            missing = missing_published_variables(context, published_keys)
            if missing:
                email = (expert.email or "").strip() or f"id={expert.id}"
                raise CampaignValidationError(
                    f"Missing published variables for {email}: {', '.join(missing)}."
                )
            custom_variables = custom_variables_for_published_keys(
                context, published_keys
            )
            prepared.append((expert, resolved, custom_variables))

        leads = [
            _instantly_lead_payload(expert, custom_variables)
            for expert, _resolved, custom_variables in prepared
        ]
        result = self.client.add_leads(
            campaign_id=campaign.external_campaign_id,
            leads=leads,
            skip_if_in_workspace=True,
        )
        lead_id_by_email = _lead_ids_by_email(result)

        created: list[GeneratedEmail] = []
        with transaction.atomic():
            for expert, resolved, _custom in prepared:
                email = ExpertDisplay.normalize_email(expert.email or "")
                created.append(
                    GeneratedEmail.objects.create(
                        created_by=editor,
                        expert_search=expert_search,
                        outreach_campaign=campaign,
                        expert_name=format_expert_name_from_raw(
                            resolved.get("name") or ""
                        ),
                        expert_title=(expert.academic_title or "").strip(),
                        expert_affiliation=(expert.affiliation or "").strip(),
                        expert_email=email,
                        expertise=(expert.expertise or "").strip(),
                        email_subject=campaign.published_subject or "",
                        email_body=campaign.published_body or "",
                        status=GeneratedEmail.Status.SENDING,
                        channels=[GeneratedEmail.Channel.EMAIL],
                        external_lead_id=lead_id_by_email.get(email, ""),
                    )
                )
        return created


def _load_experts_for_search(
    expert_search: ExpertSearch, expert_ids: list[int]
) -> list[Expert]:
    """Return experts in request order; all must belong to the search and have email."""
    unique_ids = list(dict.fromkeys(expert_ids))
    linked = {
        se.expert_id: se.expert
        for se in SearchExpert.objects.filter(
            expert_search=expert_search,
            expert_id__in=unique_ids,
        ).select_related("expert")
    }
    missing_ids = [eid for eid in unique_ids if eid not in linked]
    if missing_ids:
        raise CampaignValidationError(
            "Experts not found in search: "
            + ", ".join(str(eid) for eid in missing_ids)
            + "."
        )

    experts: list[Expert] = []
    for eid in unique_ids:
        expert = linked[eid]
        if not ExpertDisplay.normalize_email(expert.email or ""):
            raise CampaignValidationError(
                f"Expert id={expert.id} has no email address."
            )
        experts.append(expert)
    return experts


def _instantly_lead_payload(expert: Expert, custom_variables: dict[str, str]) -> dict:
    email = ExpertDisplay.normalize_email(expert.email or "")
    return {
        "email": email,
        "first_name": (expert.first_name or "").strip(),
        "last_name": (expert.last_name or "").strip(),
        "company_name": (expert.affiliation or "").strip(),
        "custom_variables": {
            key: (value if value is not None else "")
            for key, value in custom_variables.items()
        },
    }


def _lead_ids_by_email(result: dict | None) -> dict[str, str]:
    if not isinstance(result, dict):
        return {}
    created = result.get("created_leads") or []
    mapping: dict[str, str] = {}
    if not isinstance(created, list):
        return mapping
    for row in created:
        if not isinstance(row, dict):
            continue
        email = ExpertDisplay.normalize_email(str(row.get("email") or ""))
        lead_id = row.get("id")
        if email and lead_id is not None and str(lead_id).strip():
            mapping[email] = str(lead_id).strip()
    return mapping


def _snapshot_changed(
    campaign: OutreachCampaign,
    *,
    template: EmailTemplate,
    variable_keys: list[str],
) -> bool:
    return (
        (campaign.published_subject or "") != (template.email_subject or "")
        or (campaign.published_body or "") != (template.email_body or "")
        or list(campaign.published_variable_keys or []) != list(variable_keys)
    )


def _instantly_campaign_name(template: EmailTemplate, editor: User) -> str:
    base = (template.name or "Template").strip() or "Template"
    # Keep within a conservative Instantly name length.
    prefix = "RH "
    suffix = f" (e{editor.id})"
    max_base = 100 - len(prefix) - len(suffix)
    if len(base) > max_base:
        base = base[:max_base].rstrip()
    return f"{prefix}{base}{suffix}"


def _extract_campaign_id(result: dict | None) -> str:
    if not isinstance(result, dict):
        return ""
    for key in ("id", "campaign_id"):
        value = result.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""
