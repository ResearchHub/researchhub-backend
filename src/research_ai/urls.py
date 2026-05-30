from django.urls import path

from research_ai.views.email_views import (
    BulkGenerateEmailView,
    GeneratedEmailDetailView,
    GeneratedEmailListView,
    GenerateEmailView,
    InviteRfpApplicantsView,
    PreviewEmailView,
    SendEmailView,
)
from research_ai.views.expert_finder_views import (
    ExpertDetailView,
    ExpertListView,
    ExpertSearchAddExpertView,
    ExpertSearchDetailView,
    ExpertSearchListCreateView,
    ExpertSearchProgressStreamView,
    ExpertSearchWorkView,
    InvitedExpertEditorsOverviewView,
    InvitedExpertOverviewView,
)
from research_ai.views.template_views import TemplateDetailView, TemplateListView

urlpatterns = [
    path("expert-finder/searches/", ExpertSearchListCreateView.as_view()),
    path(
        "expert-finder/searches/<int:search_id>/",
        ExpertSearchDetailView.as_view(),
    ),
    path(
        "expert-finder/searches/<int:search_id>/experts/",
        ExpertSearchAddExpertView.as_view(),
    ),
    path(
        "expert-finder/experts/",
        ExpertListView.as_view(),
    ),
    path(
        "expert-finder/experts/<int:expert_id>/",
        ExpertDetailView.as_view(),
    ),
    path(
        "expert-finder/overview/",
        InvitedExpertOverviewView.as_view(),
    ),
    path(
        "expert-finder/editors-overview/",
        InvitedExpertEditorsOverviewView.as_view(),
    ),
    path(
        "expert-finder/work/<int:unified_document_id>/",
        ExpertSearchWorkView.as_view(),
    ),
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
    path(
        "expert-finder/rfp/<int:grant_id>/invite-applicants/",
        InviteRfpApplicantsView.as_view(),
    ),
]
