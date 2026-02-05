from django.urls import path

from research_ai.views.expert_finder_views import (
    ExpertSearchCreateView,
    ExpertSearchDetailView,
    ExpertSearchListView,
    ExpertSearchProgressStreamView,
)

urlpatterns = [
    path("expert-finder/search/", ExpertSearchCreateView.as_view()),
    path(
        "expert-finder/search/<str:search_id>/",
        ExpertSearchDetailView.as_view(),
    ),
    path("expert-finder/searches/", ExpertSearchListView.as_view()),
    path(
        "expert-finder/progress/<str:search_id>/",
        ExpertSearchProgressStreamView.as_view(),
    ),
]
