from django.conf.urls import url, include
from rest_framework.routers import DefaultRouter

from .views.thread import ThreadDocumentView

router = DefaultRouter()
threads = router.register(
    r'threads',
    ThreadDocumentView,
    basename='threaddocument'
)

urlpatterns = [
    url(r'^', include(router.urls)),
]
