import logging

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from purchase.related_models.grant_model import Grant
from research_ai.constants import DEFAULT_EMAIL_TEMPLATE_KEY, VALID_EMAIL_TEMPLATE_KEYS
from research_ai.models import ExpertSearch, GeneratedEmail
from research_ai.permissions import ResearchAIPermission
from research_ai.serializers import (
    BulkGenerateEmailRequestSerializer,
    GeneratedEmailCreateUpdateSerializer,
    GeneratedEmailSerializer,
    GenerateEmailRequestSerializer,
    InviteRfpApplicantsSerializer,
    PreviewEmailRequestSerializer,
    SendEmailRequestSerializer,
    build_expert_sources_map_for_emails,
)
from research_ai.services.expert_finder.display import ExpertDisplay
from research_ai.services.expert_finder.persist import ExpertPersist
from research_ai.services.outreach.email_generator import create_expert_email_draft
from research_ai.services.outreach.email_sender import SES_OUTREACH_DISABLED_DETAIL
from research_ai.services.outreach.proposal_draft_outreach import (
    prepare_proposal_outreach,
)
from research_ai.services.outreach.rfp_email_context import (
    get_expert_for_search_by_email,
)
from research_ai.services.outreach.rfp_invite import invite_applicants
from research_ai.services.outreach.template_variables import format_expert_name_from_raw
from research_ai.tasks import process_bulk_generate_emails_task
from user.permissions import IsModerator, UserIsEditor

logger = logging.getLogger(__name__)


def _generated_email_list_sequence_queryset(expert_search_id):
    """
    Same default ordering and search scope as GET expert-finder/emails/:
    order by -created_date; if expert_search_id is not None, filter to that search
    (equivalent to ?search_id=<id>). If None, no expert_search filter (full list).
    """
    qs = GeneratedEmail.objects.order_by("-created_date")
    if expert_search_id is not None:
        qs = qs.filter(expert_search_id=expert_search_id)
    return qs


def _apply_generated_email_list_filters(qs, query_params):
    """
    Apply optional list filters from query params.

    - ``search_id`` → expert_search_id
    - ``campaign_id`` → outreach_campaign_id
    - ``status`` → GeneratedEmail.status (must be a valid Status value)

    Invalid integer ids or unknown status yield an empty queryset.
    """
    search_id = query_params.get("search_id")
    if search_id is not None:
        try:
            qs = qs.filter(expert_search_id=int(search_id))
        except ValueError, TypeError:
            return qs.none()

    campaign_id = query_params.get("campaign_id")
    if campaign_id is not None:
        try:
            qs = qs.filter(outreach_campaign_id=int(campaign_id))
        except ValueError, TypeError:
            return qs.none()

    status_value = query_params.get("status")
    if status_value is not None:
        normalized = str(status_value).strip().lower()
        valid = {choice.value for choice in GeneratedEmail.Status}
        if normalized not in valid:
            return qs.none()
        qs = qs.filter(status=normalized)

    return qs


def _list_navigation_for_generated_email(email):
    """
    Adjacent rows in the same order as the paginated list for this email's search
    (or the unfiltered list when expert_search is null).
    """
    qs = _generated_email_list_sequence_queryset(email.expert_search_id)
    ids = list(qs.values_list("id", flat=True))
    try:
        idx = ids.index(email.id)
    except ValueError:
        return {
            "total": len(ids),
            "position": 1,
            "previous_id": None,
            "next_id": None,
        }
    n = len(ids)
    return {
        "total": n,
        "position": idx + 1,
        "previous_id": ids[idx - 1] if idx > 0 else None,
        "next_id": ids[idx + 1] if idx < n - 1 else None,
    }


def _generated_email_serializer_context(emails):
    return {
        "expert_sources_by_key": build_expert_sources_map_for_emails(emails),
    }


def _generated_email_detail_response(email):
    data = GeneratedEmailSerializer(
        email,
        context=_generated_email_serializer_context([email]),
    ).data
    data["list_navigation"] = _list_navigation_for_generated_email(email)
    return data


def _normalize_template(template: str) -> tuple[str, str | None]:
    """Return (template_key, custom_use_case or None). Supports 'custom: use case'."""
    template = (template or "").strip()
    if template.startswith("custom:"):
        return "custom", template[7:].strip() or None
    if template in VALID_EMAIL_TEMPLATE_KEYS:
        return template, None
    return "custom", template or None


def _resolve_generate_llm_params(request_data: dict, validated_data: dict):
    """
    Return (template_key, custom_use_case) for generate_expert_email.
    (None, None) means fixed template path (template was JSON null).
    """
    if "template" in request_data and request_data["template"] is None:
        return None, None
    raw = validated_data.get("template")
    if raw is None:
        return DEFAULT_EMAIL_TEMPLATE_KEY, None
    return _normalize_template(raw)


def _stored_template_for_bulk(request_data: dict, validated_data: dict) -> str | None:
    """Value persisted on GeneratedEmail.template for bulk jobs (null = fixed path)."""
    if "template" in request_data and request_data["template"] is None:
        return None
    raw = validated_data.get("template")
    if raw is None:
        return DEFAULT_EMAIL_TEMPLATE_KEY
    key, _ = _normalize_template(raw)
    return key


class GenerateEmailView(APIView):
    """
    POST /api/research_ai/expert-finder/generate-email/
    generate outreach email and save as draft.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request):
        ser = GenerateEmailRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            expert_search = ExpertSearch.objects.get(id=data["expert_search_id"])
        except ExpertSearch.DoesNotExist:
            return Response(
                {"detail": "Expert search not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        expert = get_expert_for_search_by_email(expert_search, data["expert_email"])
        if not expert:
            return Response(
                {"detail": "Expert not found in search results for this email."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        template_key, custom_use_case = _resolve_generate_llm_params(request.data, data)

        try:
            email_record = create_expert_email_draft(
                expert_search=expert_search,
                expert=expert,
                template=template_key,
                custom_use_case=custom_use_case,
                template_id=data.get("template_id"),
                user=request.user,
                proposal_draft_id=data.get("proposal_draft_id"),
            )
        except ValueError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except RuntimeError as e:
            logger.exception("Email generation failed")
            return Response(
                {"detail": str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        out = GeneratedEmailSerializer(email_record)
        return Response(out.data, status=status.HTTP_201_CREATED)


class BulkGenerateEmailView(APIView):
    """
    POST /api/research_ai/expert-finder/generate-emails-bulk/
    Create placeholders and enqueue Celery task.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request):
        ser = BulkGenerateEmailRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            expert_search = ExpertSearch.objects.get(id=data["expert_search_id"])
        except ExpertSearch.DoesNotExist:
            return Response(
                {"detail": "Expert search not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        stored_template = _stored_template_for_bulk(request.data, data)
        placeholders = []
        try:
            with transaction.atomic():
                for item in data["experts"]:
                    expert = get_expert_for_search_by_email(
                        expert_search, item["expert_email"]
                    )
                    if not expert:
                        raise ValueError(
                            "Expert not found in search results: "
                            f"{item['expert_email']}."
                        )
                    ctx = ExpertDisplay.email_generation_dict(expert)
                    prepared_outreach = None
                    if proposal_draft_id := item.get("proposal_draft_id"):
                        prepared_outreach = prepare_proposal_outreach(
                            proposal_draft_id=proposal_draft_id,
                            expert_search=expert_search,
                            expert_email=expert.email,
                            inviter=request.user,
                        )
                    email_record = GeneratedEmail.objects.create(
                        created_by=request.user,
                        expert_search=expert_search,
                        proposal_draft=(
                            prepared_outreach.draft if prepared_outreach else None
                        ),
                        note_invitation=(
                            prepared_outreach.invitation if prepared_outreach else None
                        ),
                        expert_name=format_expert_name_from_raw(ctx.get("name") or ""),
                        expert_title=expert.academic_title or "",
                        expert_affiliation=expert.affiliation or "",
                        expert_email=(expert.email or "").strip(),
                        expertise=expert.expertise or "",
                        email_subject="",
                        email_body="",
                        template=stored_template,
                        status=GeneratedEmail.Status.PROCESSING,
                    )
                    placeholders.append(email_record)
        except ValueError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ids = [p.id for p in placeholders]
        process_bulk_generate_emails_task.delay(
            ids,
            template_id=data.get("template_id"),
            created_by_id=request.user.id,
        )

        out = GeneratedEmailSerializer(placeholders, many=True)
        return Response(
            {"emails": out.data, "ids": ids},
            status=status.HTTP_202_ACCEPTED,
        )


class PreviewEmailView(APIView):
    """
    POST /api/research_ai/expert-finder/emails/preview/

    Legacy SES preview. Disabled; outreach previews/sends use Instantly campaigns.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request):
        ser = PreviewEmailRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response(
            {"detail": SES_OUTREACH_DISABLED_DETAIL},
            status=status.HTTP_410_GONE,
        )


class SendEmailView(APIView):
    """
    POST /api/research_ai/expert-finder/emails/send/

    Legacy SES send. Disabled; use POST outreach-campaigns/<id>/send/ instead.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request):
        ser = SendEmailRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response(
            {"detail": SES_OUTREACH_DISABLED_DETAIL},
            status=status.HTTP_410_GONE,
        )


class GeneratedEmailListView(APIView):
    """
    GET /api/research_ai/expert-finder/emails/ - List. POST - Create draft (no LLM).

    Optional query filters: ``search_id``, ``campaign_id`` (outreach campaign),
    ``status`` (GeneratedEmail status value, e.g. ``sending``).
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def get_queryset(self):
        return GeneratedEmail.objects.select_related(
            "created_by",
            "created_by__author_profile",
            "note_invitation",
            "proposal_draft",
            "outreach_campaign",
        ).order_by("-created_date")

    def get(self, request):
        limit = max(1, min(100, int(request.query_params.get("limit", 20))))
        offset = max(0, int(request.query_params.get("offset", 0)))
        qs = self.get_queryset()
        qs = _apply_generated_email_list_filters(qs, request.query_params)
        total = qs.count()
        items = list(qs[offset : offset + limit])
        ser = GeneratedEmailSerializer(
            items,
            many=True,
            context=_generated_email_serializer_context(items),
        )
        return Response(
            {
                "emails": ser.data,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    def post(self, request):
        ser = GeneratedEmailCreateUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        data["created_by"] = request.user
        email = GeneratedEmail.objects.create(**data)
        out = GeneratedEmailSerializer(email)
        return Response(out.data, status=status.HTTP_201_CREATED)


class GeneratedEmailDetailView(APIView):
    """
    GET /api/research_ai/expert-finder/emails/<id>/
    Retrieve one. PATCH - Update. DELETE - Delete.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def _get_email(self, request, email_id):
        try:
            email = GeneratedEmail.objects.select_related(
                "created_by",
                "created_by__author_profile",
                "note_invitation",
                "proposal_draft",
            ).get(id=int(email_id))
            return email, None
        except ValueError, TypeError, GeneratedEmail.DoesNotExist:
            return None, Response(
                {"detail": "Generated email not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def get(self, request, email_id):
        email, err = self._get_email(request, email_id)
        if err:
            return err
        return Response(_generated_email_detail_response(email))

    def patch(self, request, email_id):
        email, err = self._get_email(request, email_id)
        if err:
            return err
        previous_status = email.status
        ser = GeneratedEmailCreateUpdateSerializer(
            email, data=request.data, partial=True
        )
        ser.is_valid(raise_exception=True)
        ser.save()
        if (
            email.status == GeneratedEmail.Status.SENT
            and previous_status != GeneratedEmail.Status.SENT
        ):
            ExpertPersist.mark_last_email_sent_at(email.expert_email or "")
        return Response(_generated_email_detail_response(email))

    def delete(self, request, email_id):
        email, err = self._get_email(request, email_id)
        if err:
            return err
        email.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class InviteRfpApplicantsView(APIView):
    """POST /api/research_ai/expert-finder/rfp/<grant_id>/invite-applicants/.

    Create DRAFT invitation emails for RFP applicants. SES auto-send is
    retired; sending goes through Instantly campaigns. Authorized for the
    grant creator, listed grant contacts, and moderators.
    """

    permission_classes = [IsAuthenticated, ResearchAIPermission]

    def _get_grant_or_404(self, grant_id):
        return Grant.objects.filter(id=grant_id).first()

    def _is_authorized(self, user, grant) -> bool:
        if getattr(user, "moderator", False):
            return True
        if grant.created_by_id == user.id:
            return True
        return grant.contacts.filter(id=user.id).exists()

    def post(self, request, grant_id):
        grant = self._get_grant_or_404(grant_id)
        if grant is None:
            return Response(
                {"detail": "Grant not found."}, status=status.HTTP_404_NOT_FOUND
            )
        if not self._is_authorized(request.user, grant):
            return Response(
                {"detail": "Not allowed to invite applicants to this RFP."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if grant.status != Grant.OPEN:
            return Response(
                {"detail": "Grant must be approved and open to invite applicants."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = InviteRfpApplicantsSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            result = invite_applicants(
                grant=grant,
                inviter=request.user,
                emails=data["emails"],
            )
        except Exception as e:
            logger.exception("RFP applicant invite failed for grant=%s", grant.id)
            return Response(
                {"detail": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        # SES enqueue is retired; drafts are created for the Instantly campaign flow.
        return Response(
            {
                "queued": len(result.generated_email_ids),
                "skipped_existing": result.skipped_existing,
                "generated_email_ids": result.generated_email_ids,
            },
            status=status.HTTP_202_ACCEPTED,
        )
