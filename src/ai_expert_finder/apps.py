from django.apps import AppConfig


class AIExpertFinderConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ai_expert_finder"
    verbose_name = "AI Expert Finder"

    def ready(self):
        import ai_expert_finder.signals  # noqa: F401
