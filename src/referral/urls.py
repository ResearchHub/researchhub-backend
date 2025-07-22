from django.urls import include, path
from rest_framework.routers import DefaultRouter

from referral.views import (
    AggregateReferralMetricsViewSet,
    ReferralAssignmentViewSet,
    ReferralMetricsViewSet,
    ReferralMonitoringViewSet,
)

router = DefaultRouter()
router.register(r"metrics", ReferralMetricsViewSet, basename="referral-metrics")
router.register(
    r"aggregate-metrics",
    AggregateReferralMetricsViewSet,
    basename="aggregate-referral-metrics",
)
router.register(
    r"assignment", ReferralAssignmentViewSet, basename="referral-assignment"
)
router.register(
    r"monitoring", ReferralMonitoringViewSet, basename="referral-monitoring"
)

app_name = "referral"

urlpatterns = [
    path("", include(router.urls)),
]
