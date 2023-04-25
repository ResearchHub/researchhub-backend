from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter

from search.views import (
    CombinedView,
    HubDocumentView,
    PaperDocumentView,
    PersonDocumentView,
    PostDocumentView,
    ThreadDocumentView,
    UserDocumentView,
)

router = DefaultRouter()
person = router.register(r"person", PersonDocumentView, basename="person_document")
user = router.register(r"user", UserDocumentView, basename="user_document")
paper = router.register(r"paper", PaperDocumentView, basename="paper_document")
post = router.register(r"post", PostDocumentView, basename="post_document")
thread = router.register(r"thread", ThreadDocumentView, basename="thread_document")

hub = router.register(r"hub", HubDocumentView, basename="hub_document")

urlpatterns = [
    re_path(r"^", include(router.urls)),
    path("all/", CombinedView.as_view(), name="combined_search"),
]
