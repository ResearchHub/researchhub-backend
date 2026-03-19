from django.urls import path

from research_ai.views.email_views import (
    BulkGenerateEmailView,
    GenerateEmailView,
    GeneratedEmailDetailView,
    GeneratedEmailListView,
    PreviewEmailView,
    SendEmailView,
)
from research_ai.views.expert_finder_views import (
    ExpertSearchCreateView,
    ExpertSearchDetailView,
    ExpertSearchListView,
    ExpertSearchProgressStreamView,
    ExpertSearchWorkView,
    InvitedExpertsDocumentView,
)
from research_ai.views.proposal_review_views import (
    GrantExecutiveSummaryView,
    ProposalReviewByGrantView,
    ProposalReviewCreateView,
    ProposalReviewDetailView,
    RFPSummaryCreateView,
    RFPSummaryDetailView,
)
from research_ai.views.template_views import TemplateDetailView, TemplateListView

urlpatterns = [
    path("expert-finder/search/", ExpertSearchCreateView.as_view()),
    path(
        "expert-finder/search/<int:search_id>/",
        ExpertSearchDetailView.as_view(),
    ),
    path(
        "expert-finder/work/<int:unified_document_id>/",
        ExpertSearchWorkView.as_view(),
    ),
    path(
        "expert-finder/documents/<int:unified_document_id>/invited/",
        InvitedExpertsDocumentView.as_view(),
    ),
    path("expert-finder/searches/", ExpertSearchListView.as_view()),
    path(
        "expert-finder/progress/<int:search_id>/",
        ExpertSearchProgressStreamView.as_view(),
    ),
    path("expert-finder/generate-email/", GenerateEmailView.as_view()),
    path(
        "expert-finder/generate-emails-bulk/",
        BulkGenerateEmailView.as_view(),
    ),
    path(
        "expert-finder/emails/",
        GeneratedEmailListView.as_view(),
    ),
    path(
        "expert-finder/emails/preview/",
        PreviewEmailView.as_view(),
    ),
    path(
        "expert-finder/emails/send/",
        SendEmailView.as_view(),
    ),
    path(
        "expert-finder/emails/<int:email_id>/",
        GeneratedEmailDetailView.as_view(),
    ),
    path("expert-finder/templates/", TemplateListView.as_view()),
    path(
        "expert-finder/templates/<int:template_id>/",
        TemplateDetailView.as_view(),
    ),
    path("proposal-review/grant/<int:grant_id>/", ProposalReviewByGrantView.as_view()),
    path("proposal-review/<int:review_id>/", ProposalReviewDetailView.as_view()),
    path("proposal-review/", ProposalReviewCreateView.as_view()),
    path("rfp-summary/<int:grant_id>/", RFPSummaryDetailView.as_view()),
    path("rfp-summary/", RFPSummaryCreateView.as_view()),
    path("grant-executive-summary/", GrantExecutiveSummaryView.as_view()),
]
