from django.apps import AppConfig


class ResearchhubCommentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "researchhub_comment"

    def ready(self):
        pass
