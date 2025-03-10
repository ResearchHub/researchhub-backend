from django.urls import include, path
from rest_framework.routers import DefaultRouter

from nonprofit.views import NonprofitOrgViewSet

router = DefaultRouter()
router.register(r"", NonprofitOrgViewSet, basename="nonprofit_orgs")

urlpatterns = [
    path("", include(router.urls)),
]
