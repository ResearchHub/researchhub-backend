from django.conf.urls import url, include
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AuthorDocumentView, ComboView
from .views.thread import ThreadDocumentView
from .views.paper import PaperDocumentView
from .views.combined import search

router = DefaultRouter()
author = router.register(
    r'author',
    AuthorDocumentView,
    basename='author_document'
)
papers = router.register(
    r'papers',
    PaperDocumentView,
    basename='paper_document'
)
threads = router.register(
    r'threads',
    ThreadDocumentView,
    basename='thread_document'
)

urlpatterns = [
    url(r'^', include(router.urls)),
    path('combo/', ComboView.as_view(), name='combo_view'),
    path(r'all/', search)
]
