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
    OutreachCampaignSendSerializer,
    OutreachCampaignSerializer,
    OutreachMailboxConnectSerializer,
    OutreachMailboxSerializer,
)
from research_ai.services.outreach.campaign_service import (
    CampaignError,
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
    create_template,
    delete_template,
    get_template,
    list_templates,
    update_template,
)
from research_ai.services.outreach.webhook_service import InstantlyWebhookService
from user.permissions import IsModerator, UserIsEditor


class TemplateListView(APIView):
    """
    GET  /api/research_ai/expert-finder/templates/ - List templates.
    POST /api/research_ai/expert-finder/templates/ - Create template.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

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

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def _get_template(self, request, template_id):
        try:
            tid = int(template_id)
        except ValueError, TypeError:
            return None, Response(
                {"detail": "Invalid template ID."},
                status=status.HTTP_400_BAD_REQUEST,
            )
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
        delete_template(template_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TemplateRewriteView(APIView):
    """
    POST /api/research_ai/expert-finder/templates/<template_id>/rewrite/
    Rephrase subject/body via Bedrock and save a new EmailTemplate.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request, template_id):
        try:
            tid = int(template_id)
        except ValueError, TypeError:
            return Response(
                {"detail": "Invalid template ID."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
    Idempotent upsert of the requesting editor's Instantly campaign.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request, template_id):
        try:
            tid = int(template_id)
        except ValueError, TypeError:
            return Response(
                {"detail": "Invalid template ID."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            campaign = OutreachCampaignService().publish_template(request.user, tid)
        except CampaignTemplateNotFoundError:
            return Response(
                {"detail": "Template not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except (CampaignError, InstantlyAPIError) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        out = OutreachCampaignSerializer(campaign)
        return Response(out.data, status=status.HTTP_200_OK)


class OutreachCampaignListView(APIView):
    """
    GET /api/research_ai/expert-finder/outreach-campaigns/
    List campaigns published by the requesting editor.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

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


class OutreachCampaignSendView(APIView):
    """
    POST /api/research_ai/expert-finder/outreach-campaigns/<campaign_id>/send/
    Bulk-add experts as Instantly leads on a published campaign.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request, campaign_id):
        try:
            cid = int(campaign_id)
        except ValueError, TypeError:
            return Response(
                {"detail": "Invalid campaign ID."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = OutreachCampaignSendSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            emails = OutreachCampaignService().send_to_experts(
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
        except (CampaignError, InstantlyAPIError) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        out = GeneratedEmailSerializer(emails, many=True)
        return Response(
            {"emails": out.data, "queued": len(emails)},
            status=status.HTTP_202_ACCEPTED,
        )


class OutreachMailboxListCreateView(APIView):
    """
    GET  /api/research_ai/expert-finder/outreach-mailboxes/ - List mailboxes.
    POST /api/research_ai/expert-finder/outreach-mailboxes/ - Connect Gmail.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def get(self, request):
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
            )
        except (MailboxAlreadyConnectedError, MailboxOwnedByOtherEditorError) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        except MailboxError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except InstantlyAPIError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        out = OutreachMailboxSerializer(mailbox)
        return Response(out.data, status=status.HTTP_201_CREATED)


class OutreachMailboxDetailView(APIView):
    """
    DELETE /api/research_ai/expert-finder/outreach-mailboxes/<mailbox_id>/
    Detach a connected Gmail mailbox from Instantly and soft-delete locally.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def delete(self, request, mailbox_id):
        try:
            mid = int(mailbox_id)
        except ValueError, TypeError:
            return Response(
                {"detail": "Invalid mailbox ID."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            OutreachMailboxService().detach_mailbox(request.user, mid)
        except MailboxNotFoundError:
            return Response(
                {"detail": "Outreach mailbox not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except InstantlyAPIError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


class OutreachCapacityView(APIView):
    """
    GET /api/research_ai/expert-finder/outreach-capacity/
    Editor daily send capacity summary from local mailboxes + Instantly analytics.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def get(self, request):
        try:
            summary = OutreachMailboxService().get_capacity_summary(request.user)
        except InstantlyAPIError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(summary)


class InstantlyWebhookView(APIView):
    """
    POST /api/research_ai/expert-finder/instantly/webhook/
    Public Instantly webhook receiver; authenticated via shared secret.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

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
