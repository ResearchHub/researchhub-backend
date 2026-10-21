import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.models import OutreachMailbox
from research_ai.permissions import ResearchAIPermission
from research_ai.serializers import (
    EmailTemplateCreateSerializer,
    EmailTemplateSerializer,
    EmailTemplateUpdateSerializer,
    GeneratedEmailSerializer,
    OutreachCampaignCancelQueuedSerializer,
    OutreachCampaignPreviewSerializer,
    OutreachCampaignPublishSerializer,
    OutreachCampaignSendSerializer,
    OutreachCampaignSerializer,
    OutreachCampaignUpdateSerializer,
    OutreachMailboxAdminSerializer,
    OutreachMailboxConnectSerializer,
    OutreachMailboxOAuthInitSerializer,
    OutreachMailboxSerializer,
    OutreachMailboxUpdateSerializer,
)
from research_ai.services.outreach.campaign_service import (
    CampaignError,
    CampaignNotEmptyError,
    CampaignNotFoundError,
    CampaignNotReadyError,
    CampaignTemplateNotFoundError,
    CampaignValidationError,
    OutreachCampaignService,
)
from research_ai.services.outreach.instantly_client import InstantlyAPIError
from research_ai.services.outreach.mailbox_service import (
    MailboxAlreadyConnectedError,
    MailboxError,
    MailboxNotFoundError,
    MailboxOAuthSessionNotFoundError,
    MailboxOwnedByOtherEditorError,
    OutreachMailboxService,
)
from research_ai.services.outreach.template_rewrite_service import (
    PlaceholderMismatchError,
    TemplateNotFoundError,
    TemplateRewriteError,
    TemplateRewriteService,
)
from research_ai.services.outreach.template_service import (
    TemplateHasCampaignsError,
    create_template,
    delete_template,
    get_template,
    list_templates,
    update_template,
)
from research_ai.services.outreach.webhook_service import InstantlyWebhookService
from user.permissions import IsModerator, UserIsEditor

logger = logging.getLogger(__name__)

OUTREACH_EDITOR_PERMISSIONS = [
    IsAuthenticated,
    ResearchAIPermission,
    UserIsEditor | IsModerator,
]
INSTANTLY_WEBHOOK_PERMISSIONS = [AllowAny]
INSTANTLY_WEBHOOK_AUTHENTICATION = []


def _parse_positive_int(raw, label: str):
    """Parse a path id; return ``(value, None)`` or ``(None, error Response)``."""
    try:
        return int(raw), None
    except ValueError, TypeError:
        return None, Response(
            {"detail": f"Invalid {label}."},
            status=status.HTTP_400_BAD_REQUEST,
        )


def _mailbox_conflict_response(exc) -> Response:
    """Unified 409 body for mailbox ownership conflicts."""
    error = (
        "already_connected"
        if isinstance(exc, MailboxAlreadyConnectedError)
        else "owned_by_other"
    )
    msg = str(exc)
    return Response(
        {
            "detail": msg,
            "error": error,
            "error_description": msg,
            "status": "error",
        },
        status=status.HTTP_409_CONFLICT,
    )


def _outreach_provider_error_response(exc: InstantlyAPIError) -> Response:
    """Map outreach provider API failures to client-facing HTTP status codes."""
    logger.error(
        "Outreach provider API error status=%s body=%s: %s",
        exc.status_code,
        exc.response_body,
        exc,
    )
    if exc.status_code == 401:
        return Response(
            {
                "detail": (
                    "Outreach provider API key is invalid or missing required scopes "
                    "(accounts:create / accounts:read)."
                )
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )
    if exc.status_code == 429:
        return Response(
            {
                "detail": (
                    "Outreach provider rate limit exceeded. Please retry shortly."
                )
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    if exc.status_code == 503:
        return Response(
            {
                "detail": (
                    "Outreach provider temporarily unavailable. Please retry shortly."
                )
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )
    return Response(
        {"detail": str(exc)},
        status=status.HTTP_502_BAD_GATEWAY,
    )


class TemplateListView(APIView):
    """
    GET  /api/research_ai/expert-finder/templates/ - List templates.
    POST /api/research_ai/expert-finder/templates/ - Create template.
    """

    permission_classes = OUTREACH_EDITOR_PERMISSIONS

    def get(self, request):
        limit = max(1, min(100, int(request.query_params.get("limit", 20))))
        offset = max(0, int(request.query_params.get("offset", 0)))
        qs = list_templates()
        total = qs.count()
        items = list(qs[offset : offset + limit])
        ser = EmailTemplateSerializer(items, many=True)
        return Response(
            {
                "templates": ser.data,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    def post(self, request):
        ser = EmailTemplateCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        # Normalize optional strings to empty string for model
        create_data = {
            "name": (data.get("name") or "").strip(),
            "email_subject": (data.get("email_subject") or "").strip(),
            "email_body": (data.get("email_body") or "").strip(),
        }
        template = create_template(request.user, **create_data)
        out = EmailTemplateSerializer(template)
        return Response(out.data, status=status.HTTP_201_CREATED)


class TemplateDetailView(APIView):
    """
    GET/PATCH/DELETE /api/research_ai/expert-finder/templates/<template_id>/.
    """

    permission_classes = OUTREACH_EDITOR_PERMISSIONS

    def _get_template(self, request, template_id):
        tid, err = _parse_positive_int(template_id, "template ID")
        if err:
            return None, err
        template = get_template(tid)
        if not template:
            return None, Response(
                {"detail": "Template not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return template, None

    def get(self, request, template_id):
        template, err = self._get_template(request, template_id)
        if err:
            return err
        ser = EmailTemplateSerializer(template)
        return Response(ser.data)

    def patch(self, request, template_id):
        template, err = self._get_template(request, template_id)
        if err:
            return err
        ser = EmailTemplateUpdateSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        # Build update dict: only include provided fields
        update_data = {}
        for field in (
            "name",
            "email_subject",
            "email_body",
        ):
            if field in data:
                val = data[field]
                update_data[field] = (val or "").strip() if val is not None else ""
        template, not_found = update_template(template_id, **update_data)
        if not_found:
            return Response(
                {"detail": not_found},
                status=status.HTTP_404_NOT_FOUND,
            )
        out = EmailTemplateSerializer(template)
        return Response(out.data)

    def delete(self, request, template_id):
        _, err = self._get_template(request, template_id)
        if err:
            return err
        try:
            delete_template(template_id)
        except TemplateHasCampaignsError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class TemplateRewriteView(APIView):
    """
    POST /api/research_ai/expert-finder/templates/<template_id>/rewrite/
    Rephrase subject/body via Bedrock and save a new EmailTemplate.
    """

    permission_classes = OUTREACH_EDITOR_PERMISSIONS

    def post(self, request, template_id):
        tid, err = _parse_positive_int(template_id, "template ID")
        if err:
            return err

        try:
            template = TemplateRewriteService().rewrite_template(request.user, tid)
        except TemplateNotFoundError:
            return Response(
                {"detail": "Template not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except PlaceholderMismatchError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except TemplateRewriteError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except RuntimeError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        out = EmailTemplateSerializer(template)
        return Response(out.data, status=status.HTTP_201_CREATED)


class TemplatePublishView(APIView):
    """
    POST /api/research_ai/expert-finder/templates/<template_id>/publish/
    Always creates a new outreach campaign from the template draft.
    Body: ``{"name": "..."}`` (required campaign display name).
    """

    permission_classes = OUTREACH_EDITOR_PERMISSIONS

    def post(self, request, template_id):
        tid, err = _parse_positive_int(template_id, "template ID")
        if err:
            return err

        ser = OutreachCampaignPublishSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            campaign = OutreachCampaignService().publish_template(
                request.user,
                tid,
                name=ser.validated_data["name"],
            )
        except CampaignTemplateNotFoundError:
            return Response(
                {"detail": "Template not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except CampaignValidationError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except InstantlyAPIError as exc:
            return _outreach_provider_error_response(exc)
        except CampaignError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        out = OutreachCampaignSerializer(campaign)
        return Response(out.data, status=status.HTTP_201_CREATED)


class OutreachCampaignListView(APIView):
    """
    GET /api/research_ai/expert-finder/outreach-campaigns/
    List campaigns published by the requesting editor.
    """

    permission_classes = OUTREACH_EDITOR_PERMISSIONS

    def get(self, request):
        limit = max(1, min(100, int(request.query_params.get("limit", 20))))
        offset = max(0, int(request.query_params.get("offset", 0)))
        qs = OutreachCampaignService().list_campaigns(request.user)
        total = qs.count()
        items = list(qs[offset : offset + limit])
        ser = OutreachCampaignSerializer(items, many=True)
        return Response(
            {
                "campaigns": ser.data,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )


class OutreachCampaignDetailView(APIView):
    """
    PATCH/DELETE /api/research_ai/expert-finder/outreach-campaigns/<campaign_id>/

    PATCH: update name and/or published subject/body (synced to Instantly).
    DELETE: remove campaign when it has no linked emails (queued or sent).
    """

    permission_classes = OUTREACH_EDITOR_PERMISSIONS

    def patch(self, request, campaign_id):
        cid, err = _parse_positive_int(campaign_id, "campaign ID")
        if err:
            return err

        ser = OutreachCampaignUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            campaign = OutreachCampaignService().update_campaign(
                request.user,
                cid,
                **ser.validated_data,
            )
        except CampaignNotFoundError:
            return Response(
                {"detail": "Outreach campaign not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except CampaignNotReadyError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except CampaignValidationError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except InstantlyAPIError as exc:
            return _outreach_provider_error_response(exc)
        except CampaignError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(OutreachCampaignSerializer(campaign).data)

    def delete(self, request, campaign_id):
        cid, err = _parse_positive_int(campaign_id, "campaign ID")
        if err:
            return err

        try:
            OutreachCampaignService().delete_campaign(request.user, cid)
        except CampaignNotFoundError:
            return Response(
                {"detail": "Outreach campaign not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except CampaignNotEmptyError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        except InstantlyAPIError as exc:
            return _outreach_provider_error_response(exc)
        except CampaignError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


class OutreachCampaignActivateView(APIView):
    """
    POST /api/research_ai/expert-finder/outreach-campaigns/<campaign_id>/activate/
    Resume a paused outreach campaign (e.g. after reconnecting a mailbox).
    """

    permission_classes = OUTREACH_EDITOR_PERMISSIONS

    def post(self, request, campaign_id):
        cid, err = _parse_positive_int(campaign_id, "campaign ID")
        if err:
            return err

        try:
            campaign = OutreachCampaignService().activate_campaign(request.user, cid)
        except CampaignNotFoundError:
            return Response(
                {"detail": "Outreach campaign not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except CampaignNotReadyError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except InstantlyAPIError as exc:
            return _outreach_provider_error_response(exc)
        except CampaignError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(OutreachCampaignSerializer(campaign).data)


class OutreachCampaignSendView(APIView):
    """
    POST /api/research_ai/expert-finder/outreach-campaigns/<campaign_id>/send/
    Bulk-add experts as leads on a published outreach campaign.
    """

    permission_classes = OUTREACH_EDITOR_PERMISSIONS

    def post(self, request, campaign_id):
        cid, err = _parse_positive_int(campaign_id, "campaign ID")
        if err:
            return err

        ser = OutreachCampaignSendSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            result = OutreachCampaignService().send_to_experts(
                request.user,
                cid,
                expert_search_id=data["expert_search_id"],
                expert_ids=list(data["expert_ids"]),
            )
        except CampaignNotFoundError:
            return Response(
                {"detail": "Outreach campaign not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except (CampaignNotReadyError, CampaignValidationError) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except InstantlyAPIError as exc:
            return _outreach_provider_error_response(exc)
        except CampaignError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        emails = result["emails"]
        out = GeneratedEmailSerializer(emails, many=True)
        return Response(
            {
                "emails": out.data,
                "queued": len(emails),
                "skipped_emails": result["skipped_emails"],
            },
            status=status.HTTP_202_ACCEPTED,
        )


class OutreachCampaignCancelQueuedView(APIView):
    """
    POST /api/research_ai/expert-finder/outreach-campaigns/<campaign_id>/cancel-queued/
    """

    permission_classes = OUTREACH_EDITOR_PERMISSIONS

    def post(self, request, campaign_id):
        cid, err = _parse_positive_int(campaign_id, "campaign ID")
        if err:
            return err

        ser = OutreachCampaignCancelQueuedSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            result = OutreachCampaignService().cancel_queued_emails(
                request.user,
                cid,
                generated_email_ids=list(data["generated_email_ids"]),
            )
        except CampaignNotFoundError:
            return Response(
                {"detail": "Outreach campaign not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except (CampaignNotReadyError, CampaignValidationError) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except InstantlyAPIError as exc:
            return _outreach_provider_error_response(exc)
        except CampaignError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        out = GeneratedEmailSerializer(result["cancelled"], many=True)
        return Response(
            {
                "emails": out.data,
                "cancelled": result["cancelled_count"],
                "cancelled_ids": result["cancelled_ids"],
                "skipped_ids": result["skipped_ids"],
            },
            status=status.HTTP_200_OK,
        )


class OutreachCampaignPreviewView(APIView):
    """
    POST /api/research_ai/expert-finder/outreach-campaigns/<campaign_id>/preview/
    Render published copy for a real expert and send via provider test email.
    """

    permission_classes = OUTREACH_EDITOR_PERMISSIONS

    def post(self, request, campaign_id):
        cid, err = _parse_positive_int(campaign_id, "campaign ID")
        if err:
            return err

        ser = OutreachCampaignPreviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            result = OutreachCampaignService().preview_campaign(
                request.user,
                cid,
                expert_email=data["expert_email"],
                to_email=data["to_email"],
                expert_search_id=data.get("expert_search_id"),
                from_mailbox_id=data.get("from_mailbox_id"),
            )
        except CampaignNotFoundError:
            return Response(
                {"detail": "Outreach campaign not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except (CampaignNotReadyError, CampaignValidationError) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except InstantlyAPIError as exc:
            return _outreach_provider_error_response(exc)
        except CampaignError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "subject": result["subject"],
                "html": result["html"],
                "to_email": result["to_email"],
                "from_email": result["from_email"],
                "from_mailbox_id": result["from_mailbox_id"],
                "expert_id": result["expert_id"],
                "expert_email": result["expert_email"],
                "expert_search_id": result["expert_search_id"],
            },
            status=status.HTTP_200_OK,
        )


class OutreachMailboxListCreateView(APIView):
    """
    GET  /api/research_ai/expert-finder/outreach-mailboxes/ - List mailboxes.
        Default: caller's mailboxes. ``?scope=all`` (moderators only): every
        mailbox with editor identity + live Instantly warmup state.
    POST /api/research_ai/expert-finder/outreach-mailboxes/ - Connect Gmail.
    """

    permission_classes = OUTREACH_EDITOR_PERMISSIONS

    def get(self, request):
        scope = (request.query_params.get("scope") or "").strip().lower()
        if scope == "all":
            if not getattr(request.user, "moderator", False):
                return Response(
                    {"detail": "Only moderators can list all outreach mailboxes."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            try:
                mailboxes = OutreachMailboxService().list_all_mailboxes_for_moderator()
            except InstantlyAPIError as exc:
                return _outreach_provider_error_response(exc)
            ser = OutreachMailboxAdminSerializer(mailboxes, many=True)
            return Response({"mailboxes": ser.data})

        qs = OutreachMailbox.objects.filter(editor=request.user).order_by(
            "-created_date"
        )
        ser = OutreachMailboxSerializer(qs, many=True)
        return Response({"mailboxes": ser.data})

    def post(self, request):
        ser = OutreachMailboxConnectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            mailbox = OutreachMailboxService().connect_mailbox(
                request.user,
                email=data["email"],
                app_password=data["app_password"],
                reply_to=data.get("reply_to") or None,
            )
        except (MailboxAlreadyConnectedError, MailboxOwnedByOtherEditorError) as exc:
            return _mailbox_conflict_response(exc)
        except MailboxError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except InstantlyAPIError as exc:
            return _outreach_provider_error_response(exc)

        out = OutreachMailboxSerializer(mailbox)
        return Response(out.data, status=status.HTTP_201_CREATED)


class OutreachMailboxOAuthInitView(APIView):
    """
    POST /api/research_ai/expert-finder/outreach-mailboxes/oauth/google/init/
    Start Google Workspace OAuth for mailbox connect via the outreach provider.
    """

    permission_classes = OUTREACH_EDITOR_PERMISSIONS

    def post(self, request):
        ser = OutreachMailboxOAuthInitSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        reply_to = ser.validated_data.get("reply_to") or None

        try:
            payload = OutreachMailboxService().start_oauth(
                request.user,
                reply_to=reply_to,
            )
        except MailboxError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except InstantlyAPIError as exc:
            return _outreach_provider_error_response(exc)

        return Response(payload, status=status.HTTP_200_OK)


class OutreachMailboxOAuthSessionView(APIView):
    """
    GET /api/research_ai/expert-finder/outreach-mailboxes/oauth/session/<session_id>/
    """

    permission_classes = OUTREACH_EDITOR_PERMISSIONS

    def get(self, request, session_id):
        try:
            result = OutreachMailboxService().poll_oauth(request.user, session_id)
        except MailboxOAuthSessionNotFoundError:
            return Response(
                {"detail": "OAuth session not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except (MailboxAlreadyConnectedError, MailboxOwnedByOtherEditorError) as exc:
            return _mailbox_conflict_response(exc)
        except InstantlyAPIError as exc:
            return _outreach_provider_error_response(exc)

        if result.get("status") == "success":
            mailbox = result["mailbox"]
            return Response(
                {
                    "status": "success",
                    "email": result["email"],
                    "mailbox": OutreachMailboxSerializer(mailbox).data,
                }
            )
        return Response(result)


class OutreachMailboxDetailView(APIView):
    """
    PATCH /api/research_ai/expert-finder/outreach-mailboxes/<mailbox_id>/
        Update provider + local fields. ``reply_to`` for owner/moderator;
        ``daily_limit`` / ``warmup_enabled`` moderator-only.
    DELETE /api/research_ai/expert-finder/outreach-mailboxes/<mailbox_id>/
        Detach a connected Gmail mailbox from the outreach provider and
        soft-delete locally.
    """

    permission_classes = OUTREACH_EDITOR_PERMISSIONS

    def patch(self, request, mailbox_id):
        mid, err = _parse_positive_int(mailbox_id, "mailbox ID")
        if err:
            return err

        ser = OutreachMailboxUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        update_kwargs: dict = {}
        if "reply_to" in data:
            update_kwargs["reply_to"] = data["reply_to"]
        if "daily_limit" in data:
            update_kwargs["daily_limit"] = data["daily_limit"]
        if "warmup_enabled" in data:
            update_kwargs["warmup_enabled"] = data["warmup_enabled"]

        try:
            mailbox = OutreachMailboxService().update_mailbox(
                request.user,
                mid,
                **update_kwargs,
            )
        except MailboxNotFoundError:
            return Response(
                {"detail": "Outreach mailbox not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except MailboxError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except InstantlyAPIError as exc:
            return _outreach_provider_error_response(exc)

        if "warmup_enabled" in data:
            return Response(OutreachMailboxAdminSerializer(mailbox).data)
        return Response(OutreachMailboxSerializer(mailbox).data)

    def delete(self, request, mailbox_id):
        mid, err = _parse_positive_int(mailbox_id, "mailbox ID")
        if err:
            return err

        try:
            OutreachMailboxService().detach_mailbox(request.user, mid)
        except MailboxNotFoundError:
            return Response(
                {"detail": "Outreach mailbox not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except InstantlyAPIError as exc:
            return _outreach_provider_error_response(exc)

        return Response(status=status.HTTP_204_NO_CONTENT)


class OutreachCapacityView(APIView):
    """
    GET /api/research_ai/expert-finder/outreach-capacity/
    Refreshes mailbox daily_limit from the outreach provider, then returns
    capacity using those limits minus provider daily analytics ``sent``
    (informational only).
    """

    permission_classes = OUTREACH_EDITOR_PERMISSIONS

    def get(self, request):
        try:
            summary = OutreachMailboxService().get_capacity_summary(request.user)
        except InstantlyAPIError as exc:
            return _outreach_provider_error_response(exc)
        return Response(summary)


class InstantlyWebhookView(APIView):
    """
    POST /api/research_ai/expert-finder/instantly/webhook/
    Public Instantly webhook receiver; authenticated via shared secret.
    """

    permission_classes = INSTANTLY_WEBHOOK_PERMISSIONS
    authentication_classes = INSTANTLY_WEBHOOK_AUTHENTICATION

    def post(self, request):
        if not _instantly_webhook_authorized(request):
            return Response(
                {"detail": "Unauthorized"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        payload = request.data
        if not isinstance(payload, dict):
            return Response(
                {"detail": "Invalid payload"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        disposition = InstantlyWebhookService().handle_event(payload)
        return Response({"status": "ok", "disposition": disposition})


def _instantly_webhook_authorized(request) -> bool:
    secret = getattr(settings, "INSTANTLY_WEBHOOK_SECRET", "") or ""
    if not secret:
        return False

    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        token = auth[len("Bearer ") :].strip()
        return bool(token) and token == secret

    header_secret = (
        request.headers.get("X-Instantly-Webhook-Secret")
        or request.headers.get("X-Webhook-Secret")
        or ""
    ).strip()
    return bool(header_secret) and header_secret == secret
