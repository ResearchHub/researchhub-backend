from rest_framework import serializers

from ai_peer_review.constants import ReviewStatus
from ai_peer_review.models import ProposalReview, RFPSummary
from ai_peer_review.services.proposal_review_scoring import dimension_overall_scores


class ProposalReviewCreateSerializer(serializers.Serializer):
    unified_document_id = serializers.IntegerField()
    grant_id = serializers.IntegerField(required=False, allow_null=True)


class ProposalReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProposalReview
        fields = [
            "id",
            "unified_document_id",
            "grant_id",
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
        ]
        read_only_fields = fields


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


class GrantExecutiveSummaryRequestSerializer(serializers.Serializer):
    grant_id = serializers.IntegerField()


class GrantRfpSummaryRequestSerializer(serializers.Serializer):
    grant_id = serializers.IntegerField()
    force = serializers.BooleanField(required=False, default=False)


def build_proposal_comparison_row(review: ProposalReview | None, ud_id: int, title: str):
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
