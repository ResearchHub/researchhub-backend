from django.conf.urls import url, include
from rest_framework.routers import DefaultRouter

from .views.thread import ThreadDocumentView
from .views.paper import PaperDocumentView

router = DefaultRouter()
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
]
