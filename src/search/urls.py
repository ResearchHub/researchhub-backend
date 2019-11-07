from django.conf.urls import url, include
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CombinedView

router = DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    path('all/', CombinedView.as_view(), name='combined_search'),
]
