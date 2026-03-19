import logging

from django.db import IntegrityError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.constants import ReviewStatus
from research_ai.models import ProposalReview, RFPSummary
from research_ai.permissions import ResearchAIPermission
from research_ai.serializers import (
    GrantExecutiveSummaryRequestSerializer,
    GrantRfpSummaryRequestSerializer,
    ProposalReviewCreateSerializer,
    ProposalReviewSerializer,
    RFPSummarySerializer,
    build_proposal_comparison_row,
)
from research_ai.services.proposal_review_service import (
    validate_grant_application,
)
from research_ai.services.rfp_summary_service import run_executive_comparison
from research_ai.tasks import process_proposal_review_task, process_rfp_summary_task
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import GRANT, PREREGISTRATION
from purchase.models import Grant, GrantApplication
from user.permissions import IsModerator, UserIsEditor

logger = logging.getLogger(__name__)

_EDITOR_PERMS = [IsAuthenticated, ResearchAIPermission, UserIsEditor | IsModerator]


def _proposal_title(ud: ResearchhubUnifiedDocument) -> str:
    post = ud.posts.first()
    if post and post.title:
        return str(post.title)[:512]
    return ""


class ProposalReviewCreateView(APIView):
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
                    "status": ReviewStatus.PENDING,
                },
            )
        except IntegrityError:
            review = ProposalReview.objects.get(
                unified_document=ud, grant=grant
            )
            created = False
        if not created:
            if review.status == ReviewStatus.COMPLETED:
                return Response(
                    {
                        **ProposalReviewSerializer(review).data,
                        "already_exists": True,
                    },
                    status=status.HTTP_200_OK,
                )
            if review.status in (
                ReviewStatus.PENDING,
                ReviewStatus.PROCESSING,
            ):
                return Response(
                    ProposalReviewSerializer(review).data,
                    status=status.HTTP_202_ACCEPTED,
                )
            if review.status == ReviewStatus.FAILED:
                review.status = ReviewStatus.PENDING
                review.error_message = ""
                review.result_data = {}
                review.overall_rating = None
                review.overall_score_numeric = None
                review.save(
                    update_fields=[
                        "status",
                        "error_message",
                        "result_data",
                        "overall_rating",
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
    permission_classes = _EDITOR_PERMS

    def get(self, request, review_id):
        try:
            review = ProposalReview.objects.get(pk=review_id)
        except ProposalReview.DoesNotExist:
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(ProposalReviewSerializer(review).data)


class ProposalReviewByGrantView(APIView):
    """Comparison table: all applications to a grant + optional executive summary."""

    permission_classes = _EDITOR_PERMS

    def get(self, request, grant_id):
        try:
            grant = Grant.objects.get(pk=grant_id)
        except Grant.DoesNotExist:
            return Response(
                {"detail": "Grant not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        applications = GrantApplication.objects.filter(grant=grant).select_related(
            "preregistration_post__unified_document"
        )
        reviews = {
            r.unified_document_id: r
            for r in ProposalReview.objects.filter(
                grant_id=grant_id,
            )
        }
        proposals = []
        for app in applications:
            ud = app.preregistration_post.unified_document
            rev = reviews.get(ud.id)
            proposals.append(
                build_proposal_comparison_row(
                    rev, ud.id, _proposal_title(ud)
                )
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


class RFPSummaryCreateView(APIView):
    permission_classes = _EDITOR_PERMS

    def post(self, request):
        ser = GrantRfpSummaryRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        gid = ser.validated_data["grant_id"]
        force = ser.validated_data.get("force") or False
        try:
            grant = Grant.objects.get(pk=gid)
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
        if (
            not force
            and obj.status == ReviewStatus.COMPLETED
            and obj.summary_content.strip()
        ):
            return Response(
                {**RFPSummarySerializer(obj).data, "already_exists": True},
                status=status.HTTP_200_OK,
            )
        obj.status = ReviewStatus.PENDING
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


class RFPSummaryDetailView(APIView):
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


class GrantExecutiveSummaryView(APIView):
    permission_classes = _EDITOR_PERMS

    def post(self, request):
        ser = GrantExecutiveSummaryRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        gid = ser.validated_data["grant_id"]
        try:
            Grant.objects.get(pk=gid)
        except Grant.DoesNotExist:
            return Response(
                {"detail": "Grant not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            obj = run_executive_comparison(gid, request.user.id)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Executive summary failed grant=%s", gid)
            return Response(
                {"detail": str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            {
                "grant_id": gid,
                "executive_summary": obj.executive_comparison_summary,
                "updated_date": obj.executive_comparison_updated_date,
            }
        )
