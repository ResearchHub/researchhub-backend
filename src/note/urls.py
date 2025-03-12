from django.urls import include, path
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
# No endpoints defined

urlpatterns = [
    path("", include(router.urls)),
]
