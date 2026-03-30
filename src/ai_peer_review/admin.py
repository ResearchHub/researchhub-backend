from django.contrib import admin

from ai_peer_review.models import ProposalReview, RFPSummary


@admin.register(ProposalReview)
class ProposalReviewAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "unified_document_id",
        "grant_id",
        "status",
        "overall_rating",
        "overall_score_numeric",
        "created_date",
    )
    list_filter = ("status", "overall_rating")
    raw_id_fields = ("unified_document", "grant", "created_by")


@admin.register(RFPSummary)
class RFPSummaryAdmin(admin.ModelAdmin):
    list_display = ("id", "grant_id", "status", "created_date")
    list_filter = ("status",)
    raw_id_fields = ("grant", "created_by")
