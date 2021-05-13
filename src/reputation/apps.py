from django.apps import AppConfig


class ReputationConfig(AppConfig):
    name = 'reputation'

    def ready(self):
        import reputation.signals  # noqa: F401
