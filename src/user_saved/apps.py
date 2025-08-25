from django.apps import AppConfig


class UserSavedConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "user_saved"

    def ready(self):
        """Import signals when the app is ready"""
        # Import signals to register them
        import user_saved.signals  # noqa
