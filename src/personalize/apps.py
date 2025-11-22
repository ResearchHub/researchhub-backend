from django.apps import AppConfig


class PersonalizeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "personalize"

    def ready(self):
        import personalize.signals.paper_signals  # noqa: F401
        import personalize.signals.vote_signals  # noqa: F401
        import personalize.signals.interaction_signals  # noqa: F401
