from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter

from search.views import HubSuggesterDocumentView
from search.views.suggest import SuggestView
from search.views.unified_search import UnifiedSearchView

router = DefaultRouter()
hub_suggester = router.register(
    r"hubs", HubSuggesterDocumentView, basename="hubs_document"
)

urlpatterns = [
    path("", UnifiedSearchView.as_view(), name="unified_search"),
    path("suggest/", SuggestView.as_view(), name="suggest"),
    re_path(r"^", include(router.urls)),
]
