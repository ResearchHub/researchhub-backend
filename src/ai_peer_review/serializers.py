from rest_framework import serializers

from ai_peer_review.constants import ReviewStatus
from ai_peer_review.models import EditorialFeedback, ProposalReview, RFPSummary
from ai_peer_review.services.proposal_review_scoring import dimension_overall_scores


class ProposalReviewCreateSerializer(serializers.Serializer):
    unified_document_id = serializers.IntegerField()
    grant_id = serializers.IntegerField(required=False, allow_null=True)


class ProposalReviewSerializer(serializers.ModelSerializer):
    editorial_feedbacks = serializers.SerializerMethodField()

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
            "editorial_feedbacks",
        ]
        read_only_fields = fields

    def get_editorial_feedbacks(self, obj):
        qs = obj.editorial_feedbacks.all().order_by("created_date")
        return EditorialFeedbackSerializer(qs, many=True).data


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
    """POST body for `POST /api/ai_peer_review/rfp/<grant_id>/` (optional)."""

    force = serializers.BooleanField(required=False, default=False)


class EditorialFeedbackSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)

    class Meta:
        model = EditorialFeedback
        fields = [
            "id",
            "proposal_review_id",
            "unified_document_id",
            "user_id",
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
            "proposal_review_id",
            "unified_document_id",
            "user_id",
            "created_date",
            "updated_date",
        ]


class EditorialFeedbackCreateSerializer(serializers.ModelSerializer):
    proposal_review_id = serializers.PrimaryKeyRelatedField(
        queryset=ProposalReview.objects.all(),
        source="proposal_review",
        write_only=True,
    )

    class Meta:
        model = EditorialFeedback
        fields = [
            "proposal_review_id",
            "fundability_expert",
            "feasibility_expert",
            "novelty_expert",
            "impact_expert",
            "reproducibility_expert",
            "expert_insights",
        ]

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)


class EditorialFeedbackUpdateSerializer(serializers.ModelSerializer):
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
            "fundability_expert": {"required": False},
            "feasibility_expert": {"required": False},
            "novelty_expert": {"required": False},
            "impact_expert": {"required": False},
            "reproducibility_expert": {"required": False},
            "expert_insights": {"required": False},
        }


def build_proposal_comparison_row(
    review: ProposalReview | None,
    ud_id: int,
    title: str,
    editorial_feedbacks: list | None = None,
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
        "editorial_feedbacks": editorial_feedbacks or [],
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
