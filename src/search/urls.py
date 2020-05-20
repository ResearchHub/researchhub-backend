from django.conf.urls import url, include
from django.urls import path
from rest_framework.routers import DefaultRouter

from search.views import (
    AuthorDocumentView,
    CombinedView,
    PaperDocumentView,
    ThreadDocumentView,
    # crossref,
    # orcid
)
from search.views.combined import MatchingPaperSearch

router = DefaultRouter()
author = router.register(
    r'author',
    AuthorDocumentView,
    basename='author_document'
)
paper = router.register(
    r'paper',
    PaperDocumentView,
    basename='paper_document'
)
thread = router.register(
    r'thread',
    ThreadDocumentView,
    basename='thread_document'
)

urlpatterns = [
    url(r'^', include(router.urls)),
    path('all/', CombinedView.as_view(), name='combined_search'),
    path('match/', MatchingPaperSearch.as_view(), name='matching_search')
    # path('crossref/', crossref, name='crossref'),
    # path('orcid/', orcid, name='orcid'),
]
