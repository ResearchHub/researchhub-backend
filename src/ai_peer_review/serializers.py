from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from ai_peer_review.constants import ReviewStatus
from ai_peer_review.models import EditorialFeedback, ProposalReview, RFPSummary
from ai_peer_review.services.proposal_review_scoring import dimension_overall_scores


class ProposalReviewCreateSerializer(serializers.Serializer):
    unified_document_id = serializers.IntegerField()
    grant_id = serializers.IntegerField(required=False, allow_null=True)


class ProposalReviewSerializer(serializers.ModelSerializer):
    editorial_feedback = serializers.SerializerMethodField()

    class Meta:
        model = ProposalReview
        fields = [
            "id",
            "unified_document_id",
            "grant_id",
            "created_by_id",
            "status",
            "overall_rating",
            "overall_score_numeric",
            "result_data",
            "error_message",
            "progress",
            "current_step",
            "llm_model",
            "processing_time",
            "created_date",
            "updated_date",
            "editorial_feedback",
        ]
        read_only_fields = fields

    def get_editorial_feedback(self, obj):
        try:
            fb = obj.unified_document.ai_peer_review_editorial_feedback
        except ObjectDoesNotExist:
            return None
        return EditorialFeedbackSerializer(fb).data


class RFPSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = RFPSummary
        fields = [
            "id",
            "grant_id",
            "status",
            "summary_content",
            "executive_comparison_summary",
            "executive_comparison_updated_date",
            "error_message",
            "llm_model",
            "processing_time",
            "created_date",
            "updated_date",
        ]
        read_only_fields = fields


class RfpBriefRefreshSerializer(serializers.Serializer):
    """POST body for `POST /api/ai_peer_review/rfp/<grant_id>/`."""

    force = serializers.BooleanField(required=False, default=False)


class EditorialFeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = EditorialFeedback
        fields = [
            "id",
            "unified_document_id",
            "created_by_id",
            "updated_by_id",
            "fundability_expert",
            "feasibility_expert",
            "novelty_expert",
            "impact_expert",
            "reproducibility_expert",
            "expert_insights",
            "created_date",
            "updated_date",
        ]
        read_only_fields = [
            "id",
            "unified_document_id",
            "created_by_id",
            "updated_by_id",
            "created_date",
            "updated_date",
        ]


class EditorialFeedbackUpsertSerializer(serializers.ModelSerializer):
    """
    Create: use partial=False (all five dimension scores required).
    Update: partial=True (PATCH) or partial=False (PUT) as appropriate.
    """

    class Meta:
        model = EditorialFeedback
        fields = [
            "fundability_expert",
            "feasibility_expert",
            "novelty_expert",
            "impact_expert",
            "reproducibility_expert",
            "expert_insights",
        ]
        extra_kwargs = {
            "expert_insights": {"required": False, "allow_blank": True},
        }


def build_proposal_comparison_row(
    review: ProposalReview | None,
    ud_id: int,
    title: str,
    editorial_feedback: dict | None = None,
):
    row = {
        "unified_document_id": ud_id,
        "proposal_title": title,
        "review_id": None,
        "status": None,
        "overall_rating": None,
        "overall_score_numeric": None,
        "fundability": None,
        "feasibility": None,
        "novelty": None,
        "impact": None,
        "reproducibility": None,
        "editorial_feedback": editorial_feedback,
    }
    if review is None:
        return row
    row["review_id"] = review.id
    row["status"] = review.status
    row["overall_rating"] = review.overall_rating
    row["overall_score_numeric"] = review.overall_score_numeric
    if review.status == ReviewStatus.COMPLETED and review.result_data:
        dims = dimension_overall_scores(review.result_data)
        row["fundability"] = dims.get("fundability")
        row["feasibility"] = dims.get("feasibility")
        row["novelty"] = dims.get("novelty")
        row["impact"] = dims.get("impact")
        row["reproducibility"] = dims.get("reproducibility")
    return row
