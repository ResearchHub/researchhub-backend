from django.urls import include, path
from rest_framework.routers import DefaultRouter

from pour_review.views import PuzzleViewSet, ResultViewSet

router = DefaultRouter()
router.register(r"puzzles", PuzzleViewSet, basename="pour-review-puzzle")
router.register(r"results", ResultViewSet, basename="pour-review-result")

app_name = "pour_review"

urlpatterns = [
    path("", include(router.urls)),
]
