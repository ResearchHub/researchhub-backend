from django.conf.urls import url, include
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AuthorDocumentView,
    CombinedView,
    PaperDocumentView,
    ThreadDocumentView
)

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
]
