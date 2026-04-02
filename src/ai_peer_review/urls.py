from django.urls import path

from ai_peer_review.views.editorial_feedback_views import (
    EditorialFeedbackCreateView,
    EditorialFeedbackUpdateView,
)
from ai_peer_review.views.proposal_review_views import (
    GrantExecutiveSummaryView,
    ProposalReviewByGrantView,
    ProposalReviewCreateView,
    ProposalReviewDetailView,
    ProposalReviewPdfView,
    RFPSummaryView,
)

urlpatterns = [
    path("proposal-review/grant/<int:grant_id>/", ProposalReviewByGrantView.as_view()),
    path(
        "proposal-review/<int:review_id>/pdf/",
        ProposalReviewPdfView.as_view(),
    ),
    path("proposal-review/<int:review_id>/", ProposalReviewDetailView.as_view()),
    path("proposal-review/", ProposalReviewCreateView.as_view()),
    path("editorial-feedback/", EditorialFeedbackCreateView.as_view()),
    path(
        "editorial-feedback/<int:feedback_id>/",
        EditorialFeedbackUpdateView.as_view(),
    ),
    path(
        "rfp/<int:grant_id>/executive-summary/",
        GrantExecutiveSummaryView.as_view(),
    ),
    path("rfp/<int:grant_id>/", RFPSummaryView.as_view()),
]
