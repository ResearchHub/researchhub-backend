from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from research_ai.models import EmailTemplate, OutreachCampaign, OutreachMailbox
from research_ai.services.outreach.instantly_client import (
    DEFAULT_ACCOUNT_DAILY_LIMIT,
    DEFAULT_CAMPAIGN_SCHEDULE,
    InstantlyClient,
    InstantlyNotFoundError,
)
from research_ai.services.outreach.template_service import get_template
from research_ai.services.outreach.template_variables import (
    flatten_placeholders_for_instantly,
    published_variable_keys,
)

if TYPE_CHECKING:
    from user.related_models.user_model import User

logger = logging.getLogger(__name__)


class CampaignError(Exception):
    """Base error for campaign publish/list operations."""


class CampaignTemplateNotFoundError(CampaignError):
    """Raised when the shared EmailTemplate does not exist."""


class OutreachCampaignService:
    """Publish and list per-editor Instantly campaigns from shared templates."""

    def __init__(self, *, client: InstantlyClient | None = None):
        self.client = client if client is not None else InstantlyClient()

    def list_campaigns(self, editor: User):
        """Return the editor's published campaigns, newest first."""
        return (
            OutreachCampaign.objects.select_related("template", "editor")
            .filter(editor=editor)
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
