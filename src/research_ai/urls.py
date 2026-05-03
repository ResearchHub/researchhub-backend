from django.urls import path

from research_ai.views.email_views import (
    BulkGenerateEmailView,
    GeneratedEmailDetailView,
    GeneratedEmailListView,
    GenerateEmailView,
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
from research_ai.views.expert_finder_views_v2 import (
    ExpertSearchDetailViewV2,
    ExpertSearchListCreateViewV2,
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
        "expert-finder/v2/searches/",
        ExpertSearchListCreateViewV2.as_view(),
    ),
    path(
        "expert-finder/v2/searches/<int:search_id>/",
        ExpertSearchDetailViewV2.as_view(),
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
]
