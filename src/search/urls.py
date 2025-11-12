from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter

from search.views import HubSuggesterDocumentView, PersonDocumentView
from search.views.institution_suggester import InstitutionSuggesterDocumentView
from search.views.journal import JournalDocumentView
from search.views.person_suggester import PersonSuggesterDocumentView
from search.views.suggest import SuggestView
from search.views.unified_search import UnifiedSearchView

router = DefaultRouter()
person = router.register(r"person", PersonDocumentView, basename="person_document")
journal = router.register(r"journal", JournalDocumentView, basename="journal_document")
hub_suggester = router.register(
    r"hubs", HubSuggesterDocumentView, basename="hubs_document"
)
people_suggester = router.register(
    r"people", PersonSuggesterDocumentView, basename="people_suggester"
)
institution_suggester = router.register(
    r"institutions", InstitutionSuggesterDocumentView, basename="institution_suggester"
)

urlpatterns = [
    path("", UnifiedSearchView.as_view(), name="unified_search"),
    path("suggest/", SuggestView.as_view(), name="suggest"),
    re_path(r"^", include(router.urls)),
]
