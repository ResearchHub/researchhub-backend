from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    name = "analytics"

    def ready(self):
        """
        Import signals when the app is ready to ensure they are registered.
        """
        try:
            import analytics.signals  # noqa
        except ImportError:
            pass
