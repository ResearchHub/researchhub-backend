from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter

from search.views import (
    CitationEntryDocumentView,
    CombinedSuggestView,
    CombinedView,
    HubDocumentView,
    HubSuggesterDocumentView,
    PaperDocumentView,
    PersonDocumentView,
    PostDocumentView,
    ThreadDocumentView,
    UserSuggesterDocumentView,
)

router = DefaultRouter()
router.register(r"person", PersonDocumentView, basename="person_document")
router.register(r"paper", PaperDocumentView, basename="paper_document")
router.register(r"post", PostDocumentView, basename="post_document")
router.register(r"thread", ThreadDocumentView, basename="thread_document")
router.register(r"hub", HubDocumentView, basename="hub_document")
router.register(r"user", UserSuggesterDocumentView, basename="user_document")
router.register(
    r"citation", CitationEntryDocumentView, basename="citation_document"
)
router.register(
    r"hubs", HubSuggesterDocumentView, basename="hub_suggester_document"
)

urlpatterns = [
    re_path(r"^", include(router.urls)),
    path("all/", CombinedView.as_view(), name="combined_search"),
    path("combined-suggest/", CombinedSuggestView.as_view(), name="combined_suggester"),
]
