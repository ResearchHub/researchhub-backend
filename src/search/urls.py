from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter

from search.views import (
    CitationEntryDocumentView,
    CombinedSuggestView,
    CombinedView,
    HubDocumentView,
    HubSuggesterDocumentView,
    PaperDocumentView,
    PaperSuggesterDocumentView,
    PersonDocumentView,
    PostDocumentView,
    PostSuggesterDocumentView,
    ThreadDocumentView,
    UserSuggesterDocumentView,
)

router = DefaultRouter()
person = router.register(r"person", PersonDocumentView, basename="person_document")
# paper = router.register(r"paper", PaperDocumentView, basename="paper_document")
# post = router.register(r"post", PostDocumentView, basename="post_document")
thread = router.register(r"thread", ThreadDocumentView, basename="thread_document")
hub = router.register(r"hub", HubDocumentView, basename="hub_document")
user = router.register(r"user", UserSuggesterDocumentView, basename="user_document")
citation = router.register(
    r"citation", CitationEntryDocumentView, basename="citation_document"
)
hub_suggester = router.register(
    r"hubs", HubSuggesterDocumentView, basename="hub_document"
)
paper_suggester = router.register(
    r"paper", PaperSuggesterDocumentView, basename="paper_suggester_document"
)
post_suggester = router.register(
    r"post", PostSuggesterDocumentView, basename="post_suggester_document"
)

# combined_suggester = router.register(
#     r"combined-suggest", CombinedSuggestView.as_view(), basename="combined_suggester"
# )


urlpatterns = [
    re_path(r"^", include(router.urls)),
    path("all/", CombinedView.as_view(), name="combined_search"),
    path("combined-suggest/", CombinedSuggestView.as_view(), name="combined_suggester"),
]
