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
from search.views.institution_suggester import InstitutionSuggesterDocumentView
from search.views.journal import JournalDocumentView
from search.views.journal_suggester import JournalSuggesterDocumentView
from search.views.person_suggester import PersonSuggesterDocumentView
from search.views.suggest import SuggestView

router = DefaultRouter()
person = router.register(r"person", PersonDocumentView, basename="person_document")
paper = router.register(r"paper", PaperDocumentView, basename="paper_document")
post = router.register(r"post", PostDocumentView, basename="post_document")
thread = router.register(r"thread", ThreadDocumentView, basename="thread_document")
hub = router.register(r"hub", HubDocumentView, basename="hub_document")
journal = router.register(r"journal", JournalDocumentView, basename="journal_document")
user = router.register(r"user", UserSuggesterDocumentView, basename="user_document")
citation = router.register(
    r"citation", CitationEntryDocumentView, basename="citation_document"
)
hub_suggester = router.register(
    r"hubs", HubSuggesterDocumentView, basename="hubs_document"
)
journal_suggester = router.register(
    r"journals", JournalSuggesterDocumentView, basename="journal_suggester_document"
)
people_suggester = router.register(
    r"people", PersonSuggesterDocumentView, basename="people_suggester"
)
institution_suggester = router.register(
    r"institutions", InstitutionSuggesterDocumentView, basename="institution_suggester"
)

urlpatterns = [
    re_path(r"^", include(router.urls)),
    path("all/", CombinedView.as_view(), name="combined_search"),
    path("combined-suggest/", CombinedSuggestView.as_view(), name="combined_suggester"),
    path("suggest/", SuggestView.as_view(), name="suggest"),
]
