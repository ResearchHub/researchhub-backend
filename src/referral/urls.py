from django.urls import include, path
from rest_framework.routers import DefaultRouter

from referral.views import AggregateReferralMetricsViewSet, ReferralMetricsViewSet

router = DefaultRouter()
router.register(r"metrics", ReferralMetricsViewSet, basename="referral-metrics")
router.register(
    r"aggregate-metrics",
    AggregateReferralMetricsViewSet,
    basename="aggregate-referral-metrics",
)

app_name = "referral"

urlpatterns = [
    path("", include(router.urls)),
]
