from django.urls import include, path
from rest_framework.routers import DefaultRouter

from note.views.nonprofit_view import NonprofitOrgViewSet

router = DefaultRouter()
router.register(r"nonprofit-orgs", NonprofitOrgViewSet, basename="note-nonprofit-orgs")

urlpatterns = [
    path("", include(router.urls)),
]
