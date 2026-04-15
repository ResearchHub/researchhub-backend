from django.http import JsonResponse
from django.urls import path


def health(_request):
    return JsonResponse({"status": "ok", "app": "ai_peer_review"})


urlpatterns = [
    path("health/", health, name="ai_peer_review_health"),
]
