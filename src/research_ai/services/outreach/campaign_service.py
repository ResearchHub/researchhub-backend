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
    SearchExpert,
)
from research_ai.services.expert_finder.display import ExpertDisplay
from research_ai.services.outreach.document_context import (
    resolve_expert_search_email_document_context,
)
from research_ai.services.outreach.instantly_client import (
    DEFAULT_CAMPAIGN_SCHEDULE,
    InstantlyClient,
    InstantlyNotFoundError,
)
from research_ai.services.outreach.mailbox_service import active_mailboxes_for_editor
from research_ai.services.outreach.template_service import get_template
from research_ai.services.outreach.template_variables import (
    build_replacement_context,
    custom_variables_for_published_keys,
    flatten_placeholders_for_provider,
    format_expert_name_from_raw,
    missing_published_variables,
    published_variable_keys,
    replace_template_variables,
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
    """Publish, list, and send per-editor outreach campaigns from shared templates."""

    def __init__(self, *, client: InstantlyClient | None = None):
        self.client = client if client is not None else InstantlyClient()

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

    def publish_template(
        self, editor: User, template_id: int, *, name: str
    ) -> OutreachCampaign:
        """
        Idempotent upsert of one outreach campaign for ``(editor, template)``.

        ``name`` is required and is stored locally and sent to the provider.
        Creates and activates on first publish when the editor has active
        mailboxes.
        """
        campaign_name = _normalize_campaign_name(name)
        if not campaign_name:
            raise CampaignValidationError("Campaign name is required.")

        template = get_template(template_id)
        if template is None:
            raise CampaignTemplateNotFoundError("Template not found.")

        active_mailboxes = list(active_mailboxes_for_editor(editor))
        active_emails = [m.email for m in active_mailboxes]
        daily_limit = sum(m.daily_limit for m in active_mailboxes)
        provider_subject = flatten_placeholders_for_provider(
            template.email_subject or ""
        )
        provider_body = flatten_placeholders_for_provider(template.email_body or "")
        variable_keys = published_variable_keys(
            template.email_subject or "",
            template.email_body or "",
        )

        with transaction.atomic():
            campaign, _created = (
                OutreachCampaign.objects.select_for_update()
                .select_related("template")
                .get_or_create(
                    editor=editor,
                    template=template,
                    defaults={
                        "name": campaign_name,
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
            campaign_id = campaign.id
            snapshot_changed = _snapshot_changed(
                campaign,
                template=template,
                variable_keys=variable_keys,
            )
            name_changed = (campaign.name or "") != campaign_name
            previous_external_id = (campaign.external_campaign_id or "").strip()
            previous_status = campaign.status

        if not previous_external_id:
            external_id = self._create_provider_campaign(
                name=campaign_name,
                subject=provider_subject,
                body=provider_body,
                email_list=active_emails,
                daily_limit=daily_limit,
            )
        else:
            try:
                self._update_provider_campaign(
                    previous_external_id,
                    name=campaign_name,
                    subject=provider_subject,
                    body=provider_body,
                    email_list=active_emails,
                    daily_limit=daily_limit,
                    snapshot_changed=snapshot_changed,
                    name_changed=name_changed,
                    previous_status=previous_status,
                )
                external_id = previous_external_id
            except InstantlyNotFoundError:
                logger.info(
                    "Provider campaign %s missing; recreating for editor=%s "
                    "template=%s",
                    previous_external_id,
                    editor.id,
                    template.id,
                )
                external_id = self._create_provider_campaign(
                    name=campaign_name,
                    subject=provider_subject,
                    body=provider_body,
                    email_list=active_emails,
                    daily_limit=daily_limit,
                )

        with transaction.atomic():
            campaign = (
                OutreachCampaign.objects.select_for_update()
                .select_related("template")
                .get(id=campaign_id)
            )
            campaign.name = campaign_name
            campaign.external_campaign_id = external_id
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
                    "name",
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

    def _create_provider_campaign(
        self,
        *,
        name: str,
        subject: str,
        body: str,
        email_list: list[str],
        daily_limit: int,
    ) -> str:
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
            raise CampaignError(
                "Outreach provider create campaign response missing id."
            )
        if email_list:
            self.client.activate_campaign(external_id)
        return external_id

    def _update_provider_campaign(
        self,
        external_id: str,
        *,
        name: str,
        subject: str,
        body: str,
        email_list: list[str],
        daily_limit: int,
        snapshot_changed: bool,
        name_changed: bool,
        previous_status: str,
    ) -> None:
        update_kwargs: dict = {
            "email_list": email_list,
            "daily_limit": daily_limit,
        }
        if name_changed:
            update_kwargs["name"] = name
        if snapshot_changed:
            update_kwargs.update(
                subject=subject,
                body=body,
                campaign_schedule=DEFAULT_CAMPAIGN_SCHEDULE,
            )
        self.client.update_campaign(external_id, **update_kwargs)

        if email_list:
            if previous_status != OutreachCampaign.Status.ACTIVE:
                self.client.activate_campaign(external_id)
        else:
            self.client.pause_campaign(external_id)

    def activate_campaign(self, editor: User, campaign_id: int) -> OutreachCampaign:
        """
        Resume a paused / no-mailbox outreach campaign after mailboxes return.
        """
        campaign = (
            OutreachCampaign.objects.select_related("template")
            .filter(id=campaign_id, editor=editor)
            .first()
        )
        if campaign is None:
            raise CampaignNotFoundError("Outreach campaign not found.")
        if not campaign.external_campaign_id:
            raise CampaignNotReadyError(
                "Campaign has not been published to the outreach provider."
            )

        active_mailboxes = list(active_mailboxes_for_editor(editor))
        if not active_mailboxes:
            raise CampaignNotReadyError(
                "Connect at least one active mailbox before restoring this campaign."
            )

        email_list = [m.email for m in active_mailboxes]
        daily_limit = sum(m.daily_limit for m in active_mailboxes)
        self.client.update_campaign(
            campaign.external_campaign_id,
            email_list=email_list,
            daily_limit=daily_limit,
        )
        self.client.activate_campaign(campaign.external_campaign_id)

        campaign.status = OutreachCampaign.Status.ACTIVE
        campaign.save(update_fields=["status", "updated_date"])
        return campaign

    def send_to_experts(
        self,
        editor: User,
        campaign_id: int,
        *,
        expert_search_id: int,
        expert_ids: list[int],
    ) -> list[GeneratedEmail]:
        """
        Bulk-add experts as provider leads on an existing published campaign.

        Validates ownership and published variables. Does not enforce daily
        capacity — the provider drips sends using mailbox/campaign daily limits.
        Creates ``GeneratedEmail`` rows in ``SENDING`` (queued with the provider).
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
            raise CampaignNotReadyError(
                "Campaign has not been published to the outreach provider."
            )
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

    def cancel_queued_emails(
        self,
        editor: User,
        campaign_id: int,
        *,
        generated_email_ids: list[int],
    ) -> dict:
        """
        Remove pending provider leads and delete local ``SENDING`` rows.

        Only ``status=sending`` emails on this editor's campaign can be cancelled.
        Already-sent / other statuses are reported in ``skipped_ids``.
        """
        if not generated_email_ids:
            raise CampaignValidationError(
                "At least one generated_email id is required."
            )
        unique_ids = list(dict.fromkeys(generated_email_ids))
        if len(unique_ids) > MAX_LEADS_PER_SEND:
            raise CampaignValidationError(
                f"At most {MAX_LEADS_PER_SEND} emails can be cancelled at once."
            )

        campaign = OutreachCampaign.objects.filter(
            id=campaign_id, editor=editor
        ).first()
        if campaign is None:
            raise CampaignNotFoundError("Outreach campaign not found.")
        if not campaign.external_campaign_id:
            raise CampaignNotReadyError(
                "Campaign has not been published to the outreach provider."
            )

        rows = list(
            GeneratedEmail.objects.filter(
                id__in=unique_ids,
                outreach_campaign=campaign,
            )
        )
        by_id = {row.id: row for row in rows}
        cancellable: list[GeneratedEmail] = []
        skipped_ids: list[int] = []
        for eid in unique_ids:
            row = by_id.get(eid)
            if row is None or row.status != GeneratedEmail.Status.SENDING:
                skipped_ids.append(eid)
                continue
            cancellable.append(row)

        lead_ids = [
            (row.external_lead_id or "").strip()
            for row in cancellable
            if (row.external_lead_id or "").strip()
        ]
        if lead_ids:
            try:
                self.client.delete_leads(
                    campaign_id=campaign.external_campaign_id,
                    lead_ids=lead_ids,
                )
            except InstantlyNotFoundError:
                # Lead already gone upstream; still delete locally.
                logger.info(
                    "Provider leads already missing for campaign=%s; "
                    "deleting %s local rows",
                    campaign.external_campaign_id,
                    len(cancellable),
                )

        cancelled_ids = [row.id for row in cancellable]
        if cancelled_ids:
            GeneratedEmail.objects.filter(id__in=cancelled_ids).delete()

        return {
            # In-memory instances (pre-delete) for response serialization.
            "cancelled": cancellable,
            "cancelled_ids": cancelled_ids,
            "cancelled_count": len(cancelled_ids),
            "skipped_ids": skipped_ids,
        }

    def preview_campaign(
        self,
        editor: User,
        campaign_id: int,
        *,
        expert_email: str,
        to_email: str,
        expert_search_id: int | None = None,
        from_mailbox_id: int | None = None,
    ) -> dict:
        """
        Render published campaign copy for a real Expert and send via the
        outreach provider test-email endpoint from an active editor mailbox.

        Looks up the expert by email and builds the same replacement context as
        send (user + expert + optional search document).
        """
        to_email = (to_email or "").strip()
        if not to_email:
            raise CampaignValidationError("to_email is required.")

        normalized_expert_email = ExpertDisplay.normalize_email(expert_email)
        if not normalized_expert_email:
            raise CampaignValidationError("expert_email is required.")

        campaign = (
            OutreachCampaign.objects.select_related("template")
            .filter(id=campaign_id, editor=editor)
            .first()
        )
        if campaign is None:
            raise CampaignNotFoundError("Outreach campaign not found.")
        if not (campaign.published_subject or campaign.published_body):
            raise CampaignNotReadyError("Campaign has no published content.")

        expert = (
            Expert.objects.filter(email__iexact=normalized_expert_email)
            .order_by("id")
            .first()
        )
        if expert is None:
            raise CampaignValidationError(
                f"No expert found with email {normalized_expert_email}."
            )

        expert_search = None
        if expert_search_id is not None:
            try:
                expert_search = ExpertSearch.objects.select_related(
                    "unified_document"
                ).get(id=expert_search_id)
            except ExpertSearch.DoesNotExist as exc:
                raise CampaignValidationError("Expert search not found.") from exc
            if not SearchExpert.objects.filter(
                expert_search=expert_search, expert=expert
            ).exists():
                raise CampaignValidationError(
                    "Expert is not part of the given expert search."
                )

        mailboxes = list(active_mailboxes_for_editor(editor))
        if not mailboxes:
            raise CampaignValidationError(
                "Connect an active outreach mailbox before sending a preview."
            )

        if from_mailbox_id is not None:
            mailbox = next((m for m in mailboxes if m.id == from_mailbox_id), None)
            if mailbox is None:
                raise CampaignValidationError(
                    "Mailbox not found or not active for this editor."
                )
        else:
            mailbox = mailboxes[0]

        doc_ctx = resolve_expert_search_email_document_context(expert_search)
        resolved = ExpertDisplay.email_generation_dict(expert)
        context = build_replacement_context(
            user=editor,
            resolved_expert=resolved,
            rfp_context_dict=doc_ctx.rfp_context_dict,
            proposal_context_dict=doc_ctx.proposal_context_dict,
        )
        published_keys = list(campaign.published_variable_keys or [])
        missing = missing_published_variables(context, published_keys)
        if missing:
            raise CampaignValidationError(
                "Missing published variables for "
                f"{normalized_expert_email}: {', '.join(missing)}."
            )

        subject = replace_template_variables(campaign.published_subject or "", context)
        html = replace_template_variables(campaign.published_body or "", context)

        instantly_result = self.client.send_test_email(
            from_email=mailbox.email,
            to_email=to_email,
            subject=subject,
            html=html,
        )

        return {
            "subject": subject,
            "html": html,
            "to_email": to_email,
            "from_email": mailbox.email,
            "from_mailbox_id": mailbox.id,
            "expert_id": expert.id,
            "expert_email": ExpertDisplay.normalize_email(expert.email or ""),
            "expert_search_id": expert_search.id if expert_search else None,
            "instantly": instantly_result,
        }


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


def _normalize_campaign_name(name: str) -> str:
    """Trim and cap length for local storage / provider campaign name."""
    return (name or "").strip()[:100]


def _extract_campaign_id(result: dict | None) -> str:
    if not isinstance(result, dict):
        return ""
    for key in ("id", "campaign_id"):
        value = result.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""
