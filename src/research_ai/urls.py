from django.urls import path

from research_ai.views.email_views import (
    GenerateEmailView,
    GeneratedEmailDetailView,
    GeneratedEmailListView,
)
from research_ai.views.expert_finder_views import (
    ExpertSearchCreateView,
    ExpertSearchDetailView,
    ExpertSearchListView,
    ExpertSearchProgressStreamView,
    ExpertSearchWorkView,
)

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
    path("expert-finder/searches/", ExpertSearchListView.as_view()),
    path(
        "expert-finder/progress/<int:search_id>/",
        ExpertSearchProgressStreamView.as_view(),
    ),
    path("expert-finder/generate-email/", GenerateEmailView.as_view()),
    path(
        "expert-finder/emails/",
        GeneratedEmailListView.as_view(),
    ),
    path(
        "expert-finder/emails/<str:email_id>/",
        GeneratedEmailDetailView.as_view(),
    ),
]
