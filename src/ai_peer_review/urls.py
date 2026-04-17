from django.http import JsonResponse
from django.urls import path

from ai_peer_review.views.editorial_feedback_views import EditorialFeedbackUpsertView
from ai_peer_review.views.proposal_review_views import (
    GrantExecutiveSummaryView,
    ProposalReviewByGrantView,
    ProposalReviewCreateView,
    ProposalReviewDetailView,
    RFPSummaryView,
)


def health(_request):
    return JsonResponse({"status": "ok", "app": "ai_peer_review"})


urlpatterns = [
    path("health/", health, name="ai_peer_review_health"),
    path("proposal-review/grant/<int:grant_id>/", ProposalReviewByGrantView.as_view()),
    path("proposal-review/<int:review_id>/", ProposalReviewDetailView.as_view()),
    path("proposal-review/", ProposalReviewCreateView.as_view()),
    path(
        "editorial-feedback/<int:unified_document_id>/",
        EditorialFeedbackUpsertView.as_view(),
    ),
    path(
        "rfp/<int:grant_id>/executive-summary/",
        GrantExecutiveSummaryView.as_view(),
    ),
    path("rfp/<int:grant_id>/", RFPSummaryView.as_view()),
]
