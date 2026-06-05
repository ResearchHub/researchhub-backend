from django.apps import AppConfig


class AiPeerReviewConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ai_peer_review"

    def ready(self):
        from ai_peer_review import signals  # noqa: F401
