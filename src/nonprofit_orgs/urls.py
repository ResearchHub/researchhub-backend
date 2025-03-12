from django.urls import include, path
from rest_framework.routers import DefaultRouter

from nonprofit_orgs.views import NonprofitOrgViewSet

router = DefaultRouter()
router.register(r"orgs", NonprofitOrgViewSet, basename="nonprofit-orgs")

urlpatterns = [
    path("", include(router.urls)),
]
