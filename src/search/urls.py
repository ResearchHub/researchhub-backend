from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter

from search.views import (
    CitationEntryDocumentView,
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
person = router.register(r"person", PersonDocumentView, basename="person_document")
paper = router.register(r"paper", PaperDocumentView, basename="paper_document")
post = router.register(r"post", PostDocumentView, basename="post_document")
thread = router.register(r"thread", ThreadDocumentView, basename="thread_document")
hub = router.register(r"hub", HubDocumentView, basename="hub_document")
user = router.register(r"user", UserSuggesterDocumentView, basename="user_document")
citation = router.register(
    r"citation", CitationEntryDocumentView, basename="citation_document"
)
hub_suggester = router.register(
    r"hubs", HubSuggesterDocumentView, basename="hub_document"
)

urlpatterns = [
    re_path(r"^", include(router.urls)),
    path("all/", CombinedView.as_view(), name="combined_search"),
]
