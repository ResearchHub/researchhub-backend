from django.conf.urls import url, include
from django.urls import path
from rest_framework.routers import DefaultRouter

from search.views import (
    PersonDocumentView,
    CombinedView,
    PaperDocumentView,
    PostDocumentView,
    ThreadDocumentView,
    HubDocumentView,
)
# from search.views.combined import MatchingPaperSearch

router = DefaultRouter()
person = router.register(
    r'person',
    PersonDocumentView,
    basename='person_document'
)
paper = router.register(
    r'paper',
    PaperDocumentView,
    basename='paper_document'
)
post = router.register(
    r'post',
    PostDocumentView,
    basename='post_document'
)
thread = router.register(
    r'thread',
    ThreadDocumentView,
    basename='thread_document'
)

hub = router.register(
    r'hub',
    HubDocumentView,
    basename='hub_document'
)

urlpatterns = [
    url(r'^', include(router.urls)),
    path('all/', CombinedView.as_view(), name='combined_search'),
    # path('match/', MatchingPaperSearch.as_view(), name='matching_search')
    # path('crossref/', crossref, name='crossref'),
    # path('orcid/', orcid, name='orcid'),
]
