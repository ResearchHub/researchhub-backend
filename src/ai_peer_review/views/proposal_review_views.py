import logging

from django.db import IntegrityError
from django.db.models import Prefetch
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ai_peer_review.models import EditorialFeedback, ProposalReview, RFPSummary, Status
from ai_peer_review.permissions import AIPeerReviewPermission
from ai_peer_review.serializers import (
    EditorialFeedbackSerializer,
    ProposalReviewCreateSerializer,
    ProposalReviewSerializer,
    RfpBriefRefreshSerializer,
    RFPSummarySerializer,
    build_proposal_comparison_row,
)
from ai_peer_review.services.proposal_review_service import validate_grant_application
from ai_peer_review.services.rfp_summary_service import run_executive_comparison
from ai_peer_review.tasks import process_proposal_review_task, process_rfp_summary_task
from purchase.models import Grant, GrantApplication
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.permissions import IsModerator, UserIsEditor

logger = logging.getLogger(__name__)

_EDITOR_PERMS = [IsAuthenticated, AIPeerReviewPermission, UserIsEditor | IsModerator]


def _proposal_title(ud: ResearchhubUnifiedDocument) -> str:
    post = ud.posts.first()
    if post and post.title:
        return str(post.title)[:512]
    return ""


class ProposalReviewCreateView(APIView):
    """
    POST /api/ai_peer_review/proposal-review/ - Create or enqueue proposal review.
    """

    permission_classes = _EDITOR_PERMS

    def post(self, request):
        ser = ProposalReviewCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        uid = ser.validated_data["unified_document_id"]
        gid = ser.validated_data.get("grant_id")
        try:
            ud = ResearchhubUnifiedDocument.objects.get(pk=uid)
        except ResearchhubUnifiedDocument.DoesNotExist:
            return Response(
                {"detail": "Unified document not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if ud.document_type != PREREGISTRATION:
            return Response(
                {"detail": "Document must be a preregistration (proposal)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        grant = None
        if gid is not None:
            try:
                grant = Grant.objects.get(pk=gid)
            except Grant.DoesNotExist:
                return Response(
                    {"detail": "Grant not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            if grant.unified_document.document_type != GRANT:
                return Response(
                    {"detail": "Grant record is invalid."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                validate_grant_application(gid, uid)
            except ValueError as e:
                return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            review, created = ProposalReview.objects.get_or_create(
                unified_document=ud,
                grant=grant,
                defaults={
                    "created_by": request.user,
                    "status": Status.PENDING,
                },
            )
        except IntegrityError:
            review = ProposalReview.objects.get(unified_document=ud, grant=grant)
            created = False
        if not created:
            if review.status == Status.COMPLETED:
                return Response(
                    {
                        **ProposalReviewSerializer(review).data,
                        "already_exists": True,
                    },
                    status=status.HTTP_200_OK,
                )
            if review.status in (
                Status.PENDING,
                Status.PROCESSING,
            ):
                return Response(
                    ProposalReviewSerializer(review).data,
                    status=status.HTTP_202_ACCEPTED,
                )
            if review.status == Status.FAILED:
                review.status = Status.PENDING
                review.error_message = ""
                review.result_data = {}
                review.overall_rating = None
                review.overall_rationale = ""
                review.overall_score_numeric = None
                review.save(
                    update_fields=[
                        "status",
                        "error_message",
                        "result_data",
                        "overall_rating",
                        "overall_rationale",
                        "overall_score_numeric",
                        "updated_date",
                    ]
                )
        process_proposal_review_task.delay(review.id)
        return Response(
            ProposalReviewSerializer(review).data,
            status=status.HTTP_202_ACCEPTED,
        )


class ProposalReviewDetailView(APIView):
    """
    GET /api/ai_peer_review/proposal-review/<review_id>/ - Proposal review detail.
    """

    permission_classes = _EDITOR_PERMS

    def get(self, request, review_id):
        try:
            review = (
                ProposalReview.objects.select_related("grant", "key_insight")
                .prefetch_related(
                    "key_insight__items",
                    Prefetch(
                        "unified_document",
                        queryset=ResearchhubUnifiedDocument.objects.select_related(
                            "ai_peer_review_editorial_feedback"
                        ),
                    ),
                )
                .get(pk=review_id)
            )
        except ProposalReview.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        self.check_object_permissions(request, review)
        return Response(ProposalReviewSerializer(review).data)


class ProposalReviewByGrantView(APIView):
    """
    GET /api/ai_peer_review/proposal-review/grant/<grant_id>/ - Per-proposal rows, editorial feedback, executive summary snippet.
    """

    permission_classes = _EDITOR_PERMS

    def get(self, request, grant_id):
        try:
            grant = Grant.objects.get(pk=grant_id)
        except Grant.DoesNotExist:
            return Response(
                {"detail": "Grant not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        self.check_object_permissions(request, grant)
        applications = GrantApplication.objects.filter(grant=grant).select_related(
            "preregistration_post__unified_document"
        )
        reviews = {
            r.unified_document_id: r
            for r in ProposalReview.objects.filter(
                grant_id=grant_id,
            )
        }
        ud_ids = [app.preregistration_post.unified_document_id for app in applications]
        feedback_by_ud = {
            fb.unified_document_id: EditorialFeedbackSerializer(fb).data
            for fb in EditorialFeedback.objects.filter(
                unified_document_id__in=ud_ids
            ).prefetch_related("categories")
        }
        proposals = []
        for app in applications:
            ud = app.preregistration_post.unified_document
            rev = reviews.get(ud.id)
            ef = feedback_by_ud.get(ud.id)
            proposals.append(
                build_proposal_comparison_row(rev, ud.id, _proposal_title(ud), ef)
            )
        executive = ""
        try:
            rs = RFPSummary.objects.get(grant_id=grant_id)
            executive = rs.executive_comparison_summary or ""
        except RFPSummary.DoesNotExist:
            pass
        return Response(
            {
                "grant_id": grant.id,
                "proposals": proposals,
                "executive_summary": executive,
            }
        )


class RFPSummaryView(APIView):
    """
    GET  /api/ai_peer_review/rfp/<grant_id>/ - RFP summary status and content.
    POST /api/ai_peer_review/rfp/<grant_id>/ - Create or refresh RFP summary.
    """

    permission_classes = _EDITOR_PERMS

    def get(self, request, grant_id):
        try:
            obj = RFPSummary.objects.get(grant_id=grant_id)
        except RFPSummary.DoesNotExist:
            return Response(
                {
                    "grant_id": grant_id,
                    "status": None,
                    "summary_content": "",
                    "executive_comparison_summary": "",
                    "detail": "No RFP summary yet.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(RFPSummarySerializer(obj).data)

    def post(self, request, grant_id):
        ser = RfpBriefRefreshSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        force = ser.validated_data.get("force") or False
        try:
            grant = Grant.objects.get(pk=grant_id)
        except Grant.DoesNotExist:
            return Response(
                {"detail": "Grant not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if grant.unified_document.document_type != GRANT:
            return Response(
                {"detail": "Not a grant document."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        obj, created = RFPSummary.objects.get_or_create(
            grant=grant,
            defaults={"created_by": request.user},
        )
        if not force and obj.status == Status.COMPLETED and obj.summary_content.strip():
            return Response(
                {**RFPSummarySerializer(obj).data, "already_exists": True},
                status=status.HTTP_200_OK,
            )
        obj.status = Status.PENDING
        obj.error_message = ""
        if force:
            obj.summary_content = ""
        obj.save(
            update_fields=[
                "status",
                "error_message",
                "summary_content",
                "updated_date",
            ]
        )
        process_rfp_summary_task.delay(obj.id)
        return Response(
            RFPSummarySerializer(obj).data,
            status=status.HTTP_202_ACCEPTED,
        )


class GrantExecutiveSummaryView(APIView):
    """
    POST /api/ai_peer_review/rfp/<grant_id>/executive-summary/ - Generate executive comparison text.
    """

    permission_classes = _EDITOR_PERMS

    def post(self, request, grant_id):
        try:
            Grant.objects.get(pk=grant_id)
        except Grant.DoesNotExist:
            return Response(
                {"detail": "Grant not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            obj = run_executive_comparison(grant_id, request.user.id)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Executive summary failed grant=%s", grant_id)
            return Response(
                {"detail": str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            {
                "grant_id": grant_id,
                "executive_summary": obj.executive_comparison_summary,
                "updated_date": obj.executive_comparison_updated_date,
            }
        )
