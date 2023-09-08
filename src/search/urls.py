from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter

from search.views import (
    CombinedView,
    HubSuggesterDocumentView,
    UserSuggesterDocumentView,
)

router = DefaultRouter()
user = router.register(r"user", UserSuggesterDocumentView, basename="user_document")
hub = router.register(r"hub", HubSuggesterDocumentView, basename="hub_document")

urlpatterns = [
    re_path(r"^", include(router.urls)),
    path("all/", CombinedView.as_view(), name="combined_search"),
]
