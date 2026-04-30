from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from rest_framework import serializers

from ai_peer_review.constants import CATEGORY_KEYS
from ai_peer_review.models import (
    EditorialFeedback,
    EditorialFeedbackCategory,
    ExpertDimensionScore,
    ProposalKeyInsight,
    ProposalKeyInsightItem,
    ProposalReview,
    RFPSummary,
    Status,
)
from ai_peer_review.services.proposal_review_scoring import category_scores


class ProposalKeyInsightItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProposalKeyInsightItem
        fields = [
            "id",
            "item_type",
            "label",
            "description",
            "order",
            "created_date",
            "updated_date",
        ]
        read_only_fields = fields


class ProposalKeyInsightSerializer(serializers.ModelSerializer):
    items = ProposalKeyInsightItemSerializer(many=True, read_only=True)

    class Meta:
        model = ProposalKeyInsight
        fields = [
            "id",
            "status",
            "tldr",
            "error_message",
            "llm_model",
            "processing_time",
            "created_date",
            "updated_date",
            "items",
        ]
        read_only_fields = fields


class ProposalReviewCreateSerializer(serializers.Serializer):
    unified_document_id = serializers.IntegerField()
    grant_id = serializers.IntegerField(required=False, allow_null=True)


class ProposalReviewSerializer(serializers.ModelSerializer):
    editorial_feedback = serializers.SerializerMethodField()
    key_insight = serializers.SerializerMethodField()

    class Meta:
        model = ProposalReview
        fields = [
            "id",
            "unified_document_id",
            "grant_id",
            "created_by_id",
            "status",
            "overall_rating",
            "overall_rationale",
            "overall_confidence",
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
            "key_insight",
        ]
        read_only_fields = fields

    def get_editorial_feedback(self, obj):
        try:
            fb = obj.unified_document.ai_peer_review_editorial_feedback
        except ObjectDoesNotExist:
            return None
        return EditorialFeedbackSerializer(fb).data

    def get_key_insight(self, obj):
        try:
            ki = obj.key_insight
        except ObjectDoesNotExist:
            return None
        return ProposalKeyInsightSerializer(ki).data


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


class EditorialFeedbackCategoryEntrySerializer(serializers.Serializer):
    category_code = serializers.ChoiceField(choices=[(k, k) for k in CATEGORY_KEYS])
    score = serializers.ChoiceField(choices=ExpertDimensionScore.choices)


class EditorialFeedbackSerializer(serializers.ModelSerializer):
    categories = serializers.SerializerMethodField()

    class Meta:
        model = EditorialFeedback
        fields = [
            "id",
            "unified_document_id",
            "created_by_id",
            "updated_by_id",
            "categories",
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

    def get_categories(self, obj):
        rows = sorted(
            obj.categories.all(),
            key=lambda r: (
                CATEGORY_KEYS.index(r.category_code)
                if r.category_code in CATEGORY_KEYS
                else 99
            ),
        )
        return [{"category_code": r.category_code, "score": r.score} for r in rows]


class EditorialFeedbackUpsertSerializer(serializers.Serializer):
    """
    Create: all category codes required (partial=False on the view).
    Update: optional fields; when ``categories`` is sent, child rows are replaced.
    """

    expert_insights = serializers.CharField(required=False, allow_blank=True)
    categories = serializers.ListField(
        child=EditorialFeedbackCategoryEntrySerializer(),
        required=False,
    )

    def validate_categories(self, value):
        codes = {entry["category_code"] for entry in value}
        if len(codes) != len(value):
            raise serializers.ValidationError("Duplicate category_code entries.")
        return value

    def validate(self, attrs):
        is_create = self.context.get("is_create", False)
        cats = attrs.get("categories")
        if is_create:
            if not cats:
                raise serializers.ValidationError(
                    {"categories": "This field is required when creating feedback."}
                )
            provided = {c["category_code"] for c in cats}
            required = set(CATEGORY_KEYS)
            if provided != required:
                raise serializers.ValidationError(
                    {
                        "categories": (
                            "Must include exactly one score per category. "
                            f"Missing: {sorted(required - provided)} "
                            f"Unexpected: {sorted(provided - required)}"
                        )
                    }
                )
        return attrs


def replace_editorial_feedback_categories(
    feedback: EditorialFeedback,
    categories: list[dict],
) -> None:
    with transaction.atomic():
        feedback.categories.all().delete()
        EditorialFeedbackCategory.objects.bulk_create(
            [
                EditorialFeedbackCategory(
                    feedback=feedback,
                    category_code=row["category_code"],
                    score=row["score"],
                )
                for row in categories
            ]
        )


def serialize_ai_peer_review_summary(review: ProposalReview | None) -> dict | None:
    """Compact AI peer review payload for feeds."""
    if review is None:
        return None
    return {
        "id": review.id,
        "status": review.status,
        "overall_rating": review.overall_rating,
        "overall_score_numeric": review.overall_score_numeric,
        "grant_id": review.grant_id,
        "updated_date": (
            review.updated_date.isoformat() if review.updated_date else None
        ),
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
        "categories": None,
        "editorial_feedback": editorial_feedback,
    }
    if review is None:
        return row
    row["review_id"] = review.id
    row["status"] = review.status
    row["overall_rating"] = review.overall_rating
    row["overall_score_numeric"] = review.overall_score_numeric
    if review.status == Status.COMPLETED and review.result_data:
        cats = category_scores(review.result_data)
        row["categories"] = {k: cats.get(k) for k in CATEGORY_KEYS}
    return row
